import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
import os
from lib.machinelearning import *
import numpy as np
import csv
from config.config import *
import torch.optim as optim
import time 
from lib.combine_models import connect_model
from lib.key_poller import KeyPoller
import random

class TinyAudioNet(nn.Module):

    def __init__(self, inputsize, outputsize, only_logsoftmax=False):
        super(TinyAudioNet, self).__init__()
        self.only_logsoftmax = only_logsoftmax
        self.softmax = nn.Softmax(dim=-1)
        self.log_softmax = nn.LogSoftmax(dim=1)
        self.selu = nn.SELU()
        self.dropOut = nn.Dropout(p=0.15)
        
        self.batchNorm = nn.BatchNorm1d(inputsize)        
        self.fc1 = nn.Linear(inputsize, 512)
        self.fc2 = nn.Linear(512, 512)
        self.fc3 = nn.Linear(512, 512)
        self.fc4 = nn.Linear(512, 512)
        self.fc5 = nn.Linear(512, 256)
        self.fc6 = nn.Linear(256, outputsize)
		
    def forward(self, x):
        x = self.dropOut(self.selu( self.fc1(self.batchNorm(x))))
        x = self.dropOut(self.selu( self.fc2(x) ))
        x = self.dropOut(self.selu( self.fc3(x) ))
        x = self.dropOut(self.selu( self.fc4(x) ))
        x = self.dropOut(self.selu( self.fc5(x) ))
        x = self.fc6(x)
        if( self.training or self.only_logsoftmax ):
            return self.log_softmax(x)
        else:
            return self.softmax(x)

class TinyAudioNetEnsemble(nn.Module):
    def __init__(self, models):
        super(TinyAudioNetEnsemble, self).__init__()
        self.models = []
        self.model_length = len(models)
        for model in models:
            #model.double()
            self.models.append(model)
            
    def forward(self, x):
        out = 0
        for index, model in enumerate(self.models):
            if (index == 0):
                out = model(x)
            else:
                out = out + model(x)
        
        return out / self.model_length
            
class AudioNetTrainer:
    dataset_labels = []
    dataset_size = 0

    criterion = nn.NLLLoss()
    batch_size = 512
    validation_split = .2
    max_epochs = 300
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")
    dataset = False
    input_size = 120

    def __init__(self, dataset, net_count = 1, audio_settings = None):
        # These six used to be class attributes that __init__ only ever appended
        # to, so every trainer in a process shared one list. The CLI never
        # noticed - one process trains one model and exits. The GUI does: a
        # second run in the same session appended to the same lists, and
        # train()'s range(net_count) then picked up the *previous* run's
        # already-trained nets, sized to the previous run's label count. That is
        # what "Train another" did.
        self.nets = []
        self.optimizers = []
        self.random_seeds = []
        self.train_indices = []
        self.train_loaders = []
        self.validation_loaders = []

        self.net_count = net_count
        x, y = dataset[0]
        self.input_size = len(x)
        self.dataset_labels = dataset.get_labels()
        self.dataset = dataset
        self.dataset_size = len(dataset)
        self.audio_settings = audio_settings
        self.dataset_size = len(dataset)
        
        split = int(np.floor(self.validation_split * self.dataset_size))

        for i in range(self.net_count):
            self.nets.append(TinyAudioNet(self.input_size, len(self.dataset_labels), True))
            self.optimizers.append(optim.SGD(self.nets[i].parameters(), lr=0.003, momentum=0.9, nesterov=True))
            self.random_seeds.append(random.randint(0, 100000))
 
            # Split the dataset into validation and training data loaders
            indices = list(range(self.dataset_size))
            np.random.seed(self.random_seeds[i])
            np.random.shuffle(indices)
            train_indices, val_indices = indices[split:], indices[:split]
            self.train_indices.append( train_indices)
            
            train_sampler = SubsetRandomSampler(self.train_indices[i])
            valid_sampler = SubsetRandomSampler(val_indices)
            self.train_loaders.append(torch.utils.data.DataLoader(dataset, batch_size=self.batch_size, sampler=train_sampler, pin_memory=False, num_workers=0))
            self.validation_loaders.append(torch.utils.data.DataLoader(dataset, batch_size=self.batch_size, sampler=valid_sampler, pin_memory=False, num_workers=0))
        
    def train(self, filename, progress_callback=None, stop_check=None):
        best_accuracy = []
        combined_classifier_map = {}
        for i in range(self.net_count):
            self.nets[i] = self.nets[i].to(self.device)
            combined_classifier_map['classifier_' + str(i)] = os.path.join(CLASSIFIER_FOLDER, filename + '_' + str(i + 1) + '-BEST-weights.pth.tar')
            best_accuracy.append(0)
        starttime = int(time.time())
        combined_model = TinyAudioNetEnsemble(self.nets).to(self.device)

        input_size = 120

        # create_empty() makes recordings/models/code only.
        os.makedirs(REPLAYS_FOLDER, exist_ok=True)
        with open(REPLAYS_FOLDER + "/model_training_" + filename + str(starttime) + ".csv", 'a', newline='') as csvfile:
            headers = ['epoch', 'loss', 'avg_validation_accuracy']
            headers.extend(self.dataset_labels)
            writer = csv.DictWriter(csvfile, fieldnames=headers, delimiter=',')
            writer.writeheader()
            for epoch in range(self.max_epochs):
                # Check for external stop request
                if stop_check is not None and stop_check():
                    print("External stop requested - Stopped training loop")
                    print( "------------------------------------------------------")
                    return

                # Training
                self.dataset.set_training(True)
                epoch_loss = 0.0
                running_loss = []
                for j in range(self.net_count):
                    running_loss.append(0.0)
                    self.nets[j].train(True)

                    i = 0
                    with torch.set_grad_enabled(True):
                        st_batch= time.time()
                        for local_batch, local_labels in self.train_loaders[j]:
                            # A trailing batch of one kills the run: the net opens
                            # with BatchNorm1d, which cannot compute a variance
                            # from a single sample while training ( "Expected more
                            # than 1 value per channel" ). It happens whenever the
                            # training split is 1 more than a multiple of the batch
                            # size, so it strikes at random depending on how much
                            # was recorded. Skipped rather than drop_last=True,
                            # which would silently discard every batch - and so
                            # train on nothing - for a dataset smaller than one
                            # batch. Validation is unaffected: it runs in eval
                            # mode, where BatchNorm uses its running statistics.
                            if local_batch.size(0) < 2:
                                continue

                            # Transfer to GPU
                            local_batch, local_labels = local_batch.to(self.device), local_labels.to(self.device)

                            # Zero the gradients for this batch
                            i += 1
                            net = self.nets[j]
                            optimizer = self.optimizers[j]
                            optimizer.zero_grad()

                            # Calculating loss
                            output = net(local_batch)
                            loss = self.criterion(output, local_labels)
                            loss.backward()

                            # Prevent exploding weights
                            torch.nn.utils.clip_grad_norm_(net.parameters(),4)
                            optimizer.step()

                            running_loss[j] += loss.item()
                            epoch_loss += output.shape[0] * loss.item()

                            if( i % 10 == 0 ):
                                correct_in_minibatch = ( local_labels == output.max(dim = 1)[1] ).sum()
                                # Divide by the batch actually seen, not the
                                # nominal size: the last batch of an epoch is
                                # usually short, which understated its accuracy.
                                print('[Net: %d, %d, %5d] loss: %.3f acc: %.3f' % (j + 1, epoch + 1, i + 1, (running_loss[j] / 10), correct_in_minibatch.item()/local_labels.size(0)))
                                running_loss[j] = 0.0

                epoch_loss = epoch_loss / ( self.dataset_size * (1 - self.validation_split) )
                print('Training loss: {:.4f}'.format(epoch_loss))
                print( "Validating..." )
                for j in range(self.net_count):
                    self.nets[j].train(False)

                # Validation
                self.dataset.set_training(False)
                epoch_validation_loss = []
                correct = []
                epoch_loss = []
                accuracy = []
                combined_correct = 0
                # One per net. A single dict here left only the last net's.
                label_accuracy = []
                for j in range(self.net_count):
                    epoch_validation_loss.append(0.0)
                    correct.append(0)

                    with torch.set_grad_enabled(False):
                        accuracy_batch = {'total': {}, 'correct': {}, 'percent': {}}
                        for dataset_label in self.dataset_labels:
                            accuracy_batch['total'][dataset_label] = 0
                            accuracy_batch['correct'][dataset_label] = 0
                            accuracy_batch['percent'][dataset_label] = 0

                        for local_batch, local_labels in self.validation_loaders[j]:
                            # Transfer to GPU
                            local_batch, local_labels = local_batch.to(self.device), local_labels.to(self.device)

                            # Zero the gradients for this batch
                            optimizer = self.optimizers[j]
                            net = self.nets[j]
                            optimizer.zero_grad()

                            # Calculating loss
                            output = net(local_batch)
                            correct[j] += ( local_labels == output.max(dim = 1)[1] ).sum().item()
                            loss = self.criterion(output, local_labels)
                            epoch_validation_loss[j] += output.shape[0] * loss.item()

                            # Calculate combined accuracy on last validation pass
                            if (j + 1 == self.net_count):
                                combined_output = combined_model(local_batch)
                                combined_correct += ( local_labels == combined_output.max(dim = 1)[1] ).sum().item()

                            # Calculate the percentages
                            for index, label in enumerate(local_labels):
                                local_label_string = self.dataset_labels[label]
                                accuracy_batch['total'][local_label_string] += 1
                                if( output[index].argmax() == label ):
                                    accuracy_batch['correct'][local_label_string] += 1
                                accuracy_batch['percent'][local_label_string] = accuracy_batch['correct'][local_label_string] / accuracy_batch['total'][local_label_string]

                        label_accuracy.append(accuracy_batch['percent'])

                # Reported per sound: the mean across nets, not the last one.
                mean_label_accuracy = {}
                for dataset_label in self.dataset_labels:
                    scores = [p[dataset_label] for p in label_accuracy]
                    mean_label_accuracy[dataset_label] = (
                        sum(scores) / len(scores) if scores else 0)

                for j in range(self.net_count):
                    epoch_loss.append(epoch_validation_loss[j] / ( self.dataset_size * self.validation_split ) )
                    accuracy.append( correct[j] / ( self.dataset_size * self.validation_split ) )
                    print('[Net: %d] Validation loss: %.4f accuracy %.3f' % (j + 1, epoch_loss[j], accuracy[j]))

                # This epoch's nets scored together. Not the pkl being written,
                # which combines each net's BEST weights.
                combined_accuracy = combined_correct / ( self.dataset_size * self.validation_split )
                print('[Combined] Sum validation loss: %.4f average accuracy %.3f' % (np.sum(epoch_loss), combined_accuracy))

                csv_row = { 'epoch': epoch, 'loss': np.sum(epoch_loss), 'avg_validation_accuracy': np.average(accuracy) }
                for dataset_label in self.dataset_labels:
                    csv_row[dataset_label] = mean_label_accuracy[dataset_label]
                writer.writerow( csv_row )
                csvfile.flush()

                new_best = False
                for j in range(self.net_count):
                    current_filename = filename + '_' + str(j+1)
                    if( accuracy[j] > best_accuracy[j] ):
                        best_accuracy[j] = accuracy[j]
                        current_filename = filename + '_' + str(j+1) + '-BEST'
                        new_best = True

                    # trained_at rides inside the checkpoint because every
                    # external record of when a model was made is losable: a
                    # file mtime resets when the data dir is copied or restored,
                    # and the replay CSV is not renamed along with the model.
                    torch.save({'state_dict': self.nets[j].state_dict(),
                        'input_size': self.input_size,
                        'labels': self.dataset_labels,
                        'accuracy': accuracy[j],
                        # This net's own, per sound. last_row holds the means.
                        'label_accuracy': label_accuracy[j],
                        'combined_accuracy': combined_accuracy,
                        'last_row': csv_row,
                        'loss': epoch_loss[j],
                        'epoch': epoch,
                        'random_seed': self.random_seeds[j],
                        'trained_at': starttime,
                        }, os.path.join(CLASSIFIER_FOLDER, current_filename) + '-weights.pth.tar')

                # Persist a new combined model with the best weights if new best weights are given
                if (new_best == True):
                    print( "------------------------------------------------------")
                    print( "Persisting new combined best in " + filename )
                    print( "------------------------------------------------------")
                    connect_model( filename, combined_classifier_map, "ensemble_torch", True, self.audio_settings )

                # Notify progress callback if provided (GUI)
                if progress_callback is not None:
                    progress_callback(epoch, np.sum(epoch_loss), np.average(accuracy), mean_label_accuracy, new_best)

                # Check for stop via KeyPoller (CLI) or external stop_check (GUI)
                if stop_check is not None and stop_check():
                    print("External stop requested - Stopped training loop")
                    print( "------------------------------------------------------")
                    return

                with KeyPoller() as key_poller:
                    ESCAPEKEY = '\x1b'
                    character = key_poller.poll()
                    if ( character == ESCAPEKEY ):
                        print("Pressed escape - Stopped training loop")
                        print( "------------------------------------------------------")
                        return