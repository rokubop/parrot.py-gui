"""The Integrations tab: what a trained model is, and where to find it.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.
"""
from gui.content import tab, topic


MODEL_FILE_ROWS = (
    ("What", "A trained model is a single <code>.pkl</code> file. It carries "
             "its own nets, so nothing else has to travel with it."),
    ("Where", "<code>data/models/</code>, one file per model. The button on "
              "this tab opens that folder."),
    ("Taking it elsewhere", "Copy the file wherever the program that reads "
                            "parrot models expects it. Parrot does not "
                            "install it for you, and reads and writes nothing "
                            "outside its own data folder."),
    ("Test it first", "Models tab, <b>Test live</b>. Runs the model against "
                      "your microphone here, so you can see what it detects "
                      "before it goes anywhere."),
)


TAB = tab("integrations", "Integrations",
          "Where a trained model lives, and how to take it elsewhere.", (
    topic("model_file", "Your model file", rows=MODEL_FILE_ROWS,
          short="A trained model is one .pkl file in data/models/.",
          shown_on="Integrations tab"),
))
