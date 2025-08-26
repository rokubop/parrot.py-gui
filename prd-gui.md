# Parrot.py GUI Application - Product Requirements Document

## Project Overview

**Product Name:** Parrot.py GUI
**Version:** 2.0
**Platform:** Cross-platform desktop application (Windows, macOS, Linux)
**Technology Stack:** Python 3.12, PyQt6, pyqtgraph
**Repository:** parrot.py by chaosparrot

## Executive Summary

Transform the existing terminal-based Parrot.py audio recognition system into a modern, professional GUI application. Parrot.py enables users to interact with computers using audio patterns (clicks, sounds, speech) through machine learning classification, replacing keyboard/mouse interactions for accessibility and gaming applications.

## Current State Analysis

### Existing Functionality
- **Audio Recording & Segmentation**: Terminal-based recording with real-time sound detection
- **Machine Learning Training**: Multiple classifier types (sklearn, PyTorch) with cross-validation
- **Model Analysis**: Confusion matrices, accuracy testing, performance visualization
- **Real-time Operation**: Live audio classification with keyboard/mouse simulation
- **File Management**: Recording organization, model persistence, replay analysis
- **Advanced Features**: Model combining, audio conversion, eye-tracking integration

### Current Limitations
- **CLI-only interface** (`python settings.py`) - poor user experience
- **No visual feedback** during recording/training processes
- **Limited file management** - difficult to browse/organize recordings
- **No waveform visualization** - users can't see audio data quality
- **Complex configuration** - scattered across multiple config files
- **Poor discoverability** - features hidden in text menus

## Target Users

### Primary Users
- **Accessibility users** requiring alternative input methods
- **Gamers** seeking voice/sound-based game controls
- **Content creators** needing hands-free computer interaction
- **Researchers** working with audio classification systems

### User Personas
1. **Accessibility Advocate** - Needs reliable, easy-to-configure sound-to-action mapping
2. **Gaming Enthusiast** - Wants rapid setup and real-time feedback for game integration
3. **ML Researcher** - Requires detailed model performance analysis and experimentation tools

## Core Requirements

### 1. Recording & Audio Management (MVP PRIORITY)

#### 1.1 Recording Interface
**Priority: CRITICAL**
- **Visual recording browser** with tree structure for sound categories
- **New sound creation** with intuitive naming and categorization
- **Existing sound extension** - add recordings to existing sound categories
- **Audio device selection** dropdown with system device enumeration
- **Recording controls**: Record, Pause, Resume, Stop with keyboard shortcuts
- **Visual recording progress** with time elapsed and segments detected

#### 1.2 Waveform Analysis & Editing (CORE MVP FEATURE)
**Priority: CRITICAL**
- **Scrubbable waveform viewer** showing raw audio waveform with zoom/pan
- **Segment visualization** - display detected segments as boolean overlays/bars
- **Side-by-side or overlay display** of original waveform vs. segment detection
- **Visual segment validation** - user can see if segments match actual sound boundaries
- **Adjustable dBFS threshold** with instant visual feedback on segment changes
- **Per-recording dBFS adjustment** - fine-tune individual recordings
- **Per-sound dBFS adjustment** - set default for entire sound category
- **Re-segmentation preview** - see segment changes before applying
- **Audio playback controls** for segments and full recordings

#### 1.3 File Management
**Priority: MEDIUM**
- **Maintain existing file structure** (`data/recordings/soundname/`) for CLI compatibility
- **Recordings folder browser** with native file system integration
- **Bulk operations** - delete, move, rename multiple recordings
- **Storage usage visualization** with cleanup recommendations

### 2. Model Training & Management (MVP PRIORITY)

#### 2.1 AudioNet Training (MVP Focus)
**Priority: HIGH**
- **AudioNet model training** optimized for Talon Voice integration
- **Sound selection interface** with checkboxes for including/excluding recorded sounds
- **Training progress display** with real-time loss/accuracy metrics and ETA
- **Training configuration** with AudioNet-specific parameters
- **Model validation** with accuracy reporting and confusion matrix display

#### 2.2 Model Management
**Priority: MEDIUM**
- **Model library interface** showing existing trained models with metadata
- **Model creation wizard** with sound selection and AudioNet configuration
- **Model export/import** for sharing with Talon Voice users

#### 2.3 Advanced Model Operations (Future Phase)
**Priority: LOW - Not MVP**
- Model combining interface for ensemble and hierarchical models
- Cross-validation visualization with detailed accuracy breakdowns
- Alternative algorithm support (Random Forest, Neural Networks, PyTorch)

### 3. Live Operation & Control (Future Phase)
**Priority: LOW - Not MVP**
- Real-time monitoring and live audio visualization
- Action mapping interface and detection confidence display
- System integration and overlay windows
- `play.py` equivalent functionality

### 4. Analysis & Testing (Future Phase)
**Priority: LOW - Not MVP**
- Performance analysis tools and batch testing capabilities
- Model comparison charts and false positive/negative analysis
- Real-time testing interface for validation

### 5. Configuration & Settings

#### 5.1 Application Settings
**Priority: MEDIUM**
- **Centralized settings interface** replacing scattered config files
- **Audio configuration** (sample rates, channels, buffer sizes)
- **Recording defaults** (dBFS thresholds, device selection)
- **UI preferences** (themes, layouts, keyboard shortcuts)

#### 5.2 Advanced Configuration (Future Phase)
**Priority: LOW - Not MVP**
- Performance tuning and import/export settings
- Plugin system and scripting interface
- Integration APIs and diagnostic tools

## User Experience Requirements

### 5.1 Visual Design
**Priority: HIGH**
- **Modern, professional appearance** suitable for both accessibility and professional use
- **Dark/light theme support** with high contrast options
- **Responsive layout** adapting to different screen sizes
- **Accessibility compliance** (WCAG 2.1 AA standards)
- **Intuitive iconography** with tooltips and help text

### 5.2 Workflow Optimization
**Priority: HIGH**
- **Progressive disclosure** - simple interface for beginners, advanced options available
- **Guided setup wizard** for first-time users
- **Context-sensitive help** system with embedded tutorials
- **Keyboard navigation** support for all major functions
- **Undo/redo capabilities** for non-destructive editing

### 5.3 Performance Requirements
**Priority: HIGH**
- **Responsive UI** - no blocking operations on main thread
- **Real-time performance** - <50ms latency for audio processing
- **Memory efficiency** - handle large recording datasets without performance degradation
- **Background processing** - training and analysis without UI freezing

## Technical Architecture

### 6.1 GUI Framework Selection
**Selected: PyQt6** based on requirements analysis:
- Native cross-platform performance
- Advanced audio/visualization capabilities
- Professional appearance and extensive widget library
- Excellent threading support for real-time operations
- Strong ecosystem integration (pyqtgraph, matplotlib)

### 6.2 Key Components

#### 6.2.1 Main Application Window
```
┌─────────────────────────────────────────────────────────┐
│ Menu Bar: File | Edit | View | Tools | Help             │
├─────────────────────────────────────────────────────────┤
│ Toolbar: [Record] [Train] [Test] [Settings] [Help]     │
├─────────────────┬───────────────────────────────────────┤
│                 │                                       │
│ Navigation Tree │        Main Content Area              │
│ ├─ Recordings   │                                       │
│ ├─ Models       │        (Tabbed Interface)             │
│ ├─ Analysis     │                                       │
│ └─ Settings     │                                       │
│                 │                                       │
└─────────────────┴───────────────────────────────────────┘
│ Status Bar: Ready | Device: Headset | Model: active.pkl │
└─────────────────────────────────────────────────────────┘
```

#### 6.2.2 Recording Interface Layout (MVP FOCUS)
```
┌─────────────────┬───────────────────────────────────────┐
│ Sounds Library  │ Waveform Analysis (CORE FEATURE)      │
│ ├─ click        │ ┌─────────────────────────────────────┐ │
│ │  ├─ rec1.wav  │ │  Original Waveform                  │ │
│ │  └─ rec2.wav  │ │  [Audio waveform visualization]     │ │
│ ├─ whistle      │ └─────────────────────────────────────┘ │
│ └─ [+ New]      │ ┌─────────────────────────────────────┐ │
│                 │ │  Segment Detection (Boolean Bars)   │ │
│ Recording Info  │ │  [■■■  ■■■■■  ■■  ■■■■■■]         │ │
│ ├─ Duration: 45s│ └─────────────────────────────────────┘ │
│ ├─ Segments: 23 │ dBFS: [-20.5] [Apply] [Reset]         │
│ └─ Quality: Good│ [▶ Play] [⏸ Pause] [⏹ Stop]           │
│                 │ ┌─────────────────────────────────────┐ │
│ [Record New]    │ │ Device: [Microphone v] [● REC]       │ │
│ [dBFS Settings] │ │ Status: Ready to record              │ │
│                 │ │ [Global dBFS] [Per-Sound dBFS]       │ │
└─────────────────┴───────────────────────────────────────┘
```

#### 6.2.3 AudioNet Training Interface (MVP FOCUS)
```
┌─────────────────┬───────────────────────────────────────┐
│ Sound Selection │ AudioNet Training Configuration       │
│ ☑ click (145)   │ Model Name: [talon_model_v1         ] │
│ ☑ whistle (67)  │ Algorithm: [AudioNet (Talon)      v] │
│ ☐ background    │ Features: [Auto-configured         ] │
│ ☑ silence (auto)│ ┌─────────────────────────────────────┐ │
│                 │ │ Training Progress                   │ │
│ Model Info      │ │ Epoch 15/50 ████████░░ 30%         │ │
│ ├─ Classes: 3   │ │ Loss: 0.0234  Accuracy: 94.2%      │ │
│ ├─ Samples: 1.2k│ │ ETA: 2m 15s                        │ │
│ └─ Features: 39 │ └─────────────────────────────────────┘ │
│                 │ [Start Training] [Pause] [Stop]       │
│ [Select All]    │ ┌─────────────────────────────────────┐ │
│ [Clear All]     │ │     Training Metrics Graph         │ │
│ [Refresh]       │ │     [Accuracy and Loss curves]     │ │
└─────────────────┴─────────────────────────────────────────┘
```

### 6.3 Implementation Strategy

#### MVP Phase 1: Core Recording Experience (Weeks 1-4)
- **Main window structure** with PyQt6 framework
- **Smart dependency manager** with Windows-first platform detection
- **Recording interface** with sound library browser
- **Waveform visualization** using pyqtgraph with segment overlay display
- **dBFS threshold adjustment** with real-time preview

#### MVP Phase 2: Segment Analysis & Validation (Weeks 5-6)
- **Scrubbable waveform viewer** with zoom and pan controls
- **Side-by-side/overlay segment comparison** for visual validation
- **Per-recording and per-sound dBFS configuration**
- **Audio playback controls** for segments and full recordings

#### MVP Phase 3: AudioNet Training (Weeks 7-9)
- **Sound selection interface** for training data preparation
- **AudioNet integration** with Talon Voice compatibility
- **Training progress visualization** with real-time metrics
- **Model management** (save, load, basic validation)

#### MVP Phase 4: Polish & Windows Distribution (Weeks 10-11)
- **Installation system** with automatic dependency management
- **Settings management** - centralized configuration
- **Error handling and user feedback** systems
- **Windows installer and distribution**

#### Future Phases (Post-MVP):
- **Cross-platform support** (macOS, Linux)
- **Advanced model types** (ensemble, hierarchical)
- **Live operation mode** (`play.py` equivalent)
- **Analysis and testing tools**
- **Audio conversion and advanced features**

## Success Metrics

### MVP Success Metrics
- **Recording Quality Validation**: 95% of users can identify segment accuracy issues within first session
- **dBFS Adjustment Efficiency**: <30 seconds to adjust and re-segment a recording
- **Training Success Rate**: 90% of AudioNet training sessions complete successfully with >80% accuracy
- **Windows Installation Success**: 95% one-click installation success rate on Windows 10/11
- **Setup time reduction**: <5 minutes from download to first trained model (vs. 60+ minutes CLI)

### Technical Performance Metrics (MVP)
- **Waveform rendering performance**: <100ms to load and display 30-second recordings
- **dBFS adjustment responsiveness**: <50ms visual feedback for threshold changes
- **UI responsiveness**: <100ms response time for all user interactions
- **Memory efficiency**: Support 1GB+ recording datasets without performance loss

### User Experience Metrics (MVP)
- **Feature discovery**: 100% of users find waveform/segment comparison within first 5 minutes
- **Error reduction**: 80% fewer "bad model" issues due to improved segment validation
- **User retention**: 90% of users complete first record→train→validate workflow
- **Task completion**: Record new sound and train model in <10 minutes for experienced users

### 7. Dependency Management & Installation

#### 7.1 Current Challenges
**Priority: CRITICAL**
The current installation process has significant user experience issues:
- **Manual dependency installation** via CLI commands (`pip install -r requirements-windows.txt`)
- **Platform-specific requirements** (Windows vs. POSIX) requiring user platform detection
- **Complex system dependencies** (portaudio, FFMPEG, speech recognition)
- **Version compatibility issues** (Python 3.8-3.12, audiomentations<=0.40.0)
- **Missing dependencies cause runtime crashes** rather than graceful handling

#### 7.2 Recommended Installation Strategy
**Hybrid Approach: Installer + First-Run Setup**

##### Phase 1: Application Distribution
**Pre-packaged Installer Approach:**
```
Option A: PyInstaller/cx_Freeze Bundle
├─ Self-contained executable with Python runtime
├─ Core PyQt6 dependencies bundled
├─ Platform-specific binaries included
└─ ~200-300MB download size

Option B: Lightweight Installer + Package Manager
├─ Small installer (~50MB) with Python detection
├─ Automatic platform detection (Windows/macOS/Linux)
├─ Smart dependency resolution and installation
└─ Fallback to manual installation guides
```

**Recommended: Option B - Smart Installer**

##### Phase 2: First-Run Dependency Setup
**Integrated Package Manager Interface:**

```
┌─────────────────────────────────────────────────────────┐
│ Parrot.py Setup - Dependency Installation               │
├─────────────────────────────────────────────────────────┤
│ Checking system requirements...                         │
│ ✓ Python 3.12 detected                                 │
│ ✓ pip available                                         │
│ ⚠ Audio system check required                          │
│                                                         │
│ Installing core dependencies:                           │
│ [████████████████████████████████████████████████] 85% │
│ Installing: torch (2.1.0) - 150MB remaining...         │
│                                                         │
│ Optional components:                                    │
│ ☑ PyTorch GPU Support (CUDA) - 2.5GB                  │
│ ☑ Speech Recognition (Windows only)                    │
│ ☑ FFMPEG Audio Conversion                              │
│ ☐ Eye Tracking Integration                             │
│                                                         │
│ [Continue] [Install All] [Custom Setup] [Skip]         │
└─────────────────────────────────────────────────────────┘
```

#### 7.3 Technical Implementation

##### 7.3.1 Smart Dependency Detection
```python
# Pseudo-code for dependency manager
class DependencyManager:
    def detect_platform(self):
        # Auto-detect Windows/macOS/Linux
        # Return appropriate requirements file

    def check_system_requirements(self):
        # Verify Python version (3.8-3.12)
        # Test audio system (portaudio, microphone access)
        # Check available disk space (3GB+ for full install)

    def install_dependencies(self, requirements_set):
        # Progressive installation with progress feedback
        # Graceful failure handling with alternative suggestions
        # Automatic retry with different package sources

    def verify_installation(self):
        # Test import of critical packages
        # Audio system functionality test
        # Model loading verification
```

##### 7.3.2 Graceful Degradation Strategy
```python
# Feature availability based on installed dependencies
FEATURE_MATRIX = {
    'core_audio': ['pyaudio', 'numpy', 'scikit-learn'],
    'neural_networks': ['torch'],
    'gpu_acceleration': ['torch[cuda]'],
    'speech_recognition': ['dragonfly2', 'pywin32'],  # Windows only
    'audio_conversion': ['ffmpeg'],
    'advanced_visualization': ['matplotlib', 'pandas']
}

# Enable/disable features based on available dependencies
def initialize_application():
    available_features = check_available_features()
    configure_ui_based_on_features(available_features)
```

#### 7.4 Installation Workflow Options

##### Option 1: First-Run Setup Wizard (Recommended)
**When:** Application starts for the first time
**Advantages:**
- User can see the application interface immediately
- Progressive disclosure of complexity
- Can skip optional dependencies initially
- Better error handling and user feedback

**Implementation:**
1. **Minimal startup** - Load GUI with core PyQt6 only
2. **Dependency checker** runs in background thread
3. **Setup wizard** appears if dependencies missing
4. **Progressive installation** with cancel/retry options
5. **Feature unlock** as dependencies become available

##### Option 2: Pre-Installation Validation
**When:** Before application can start
**Advantages:**
- Ensures fully functional application on first run
- Traditional software installation experience
- Prevents runtime dependency errors

**Implementation:**
1. **Installation script** runs before main application
2. **System validation** and dependency installation
3. **Success verification** before application access
4. **Installation logs** for troubleshooting

##### Option 3: Background Installation
**When:** After initial application launch
**Advantages:**
- Immediate application access
- Non-blocking installation process
- Progressive feature enablement

**Implementation:**
1. **Core functionality** available immediately
2. **Background installer** downloads and installs packages
3. **Notification system** when new features become available
4. **Restart prompt** when installation complete

#### 7.5 Platform-Specific Considerations

##### Windows-Specific Requirements
```yaml
core_packages:
  - pyaudio
  - pywin32 (for speech recognition)
  - pydirectinput (for DirectX games)

system_requirements:
  - Windows Speech Recognition (optional)
  - NIRCMD.exe (for volume control)
  - Visual C++ Redistributable (for some packages)

installation_method:
  - pip install with Windows-specific requirements-windows.txt
  - Automatic Visual Studio Build Tools detection
  - Windows Store Python compatibility check
```

##### macOS-Specific Requirements
```yaml
system_dependencies:
  - portaudio (via Homebrew)
  - libsndfile (for M1 compatibility)
  - Accessibility permissions

installation_challenges:
  - M1/Intel architecture detection
  - Homebrew dependency management
  - Python path configuration
  - Audio permission prompts

installation_method:
  - Homebrew integration for system dependencies
  - Virtual environment creation
  - Permission setup automation
```

##### Linux-Specific Requirements
```yaml
system_dependencies:
  - portaudio-dev
  - python3-tk
  - ALSA/PulseAudio detection

installation_method:
  - Package manager detection (apt, yum, pacman)
  - System dependency installation via sudo
  - Audio system configuration
  - X11 dependency verification
```

#### 7.6 Error Handling & Recovery

##### Installation Failure Scenarios
1. **Network connectivity issues**
   - Offline package cache
   - Alternative package sources
   - Manual installation guides

2. **Insufficient permissions**
   - User-space installation options
   - Virtual environment fallback
   - Elevated permission prompts

3. **Package compilation failures**
   - Pre-compiled wheel alternatives
   - Docker container option
   - System-specific troubleshooting guides

4. **Dependency conflicts**
   - Version pinning strategies
   - Isolated environment creation
   - Conflict resolution suggestions

#### 7.7 Maintenance & Updates

##### Automatic Update System
- **Dependency version checking** against known compatible versions
- **Security update notifications** for critical packages
- **Feature update opt-in** for new optional dependencies
- **Rollback capabilities** for failed updates

##### Health Monitoring
- **Startup dependency verification** with repair options
- **Performance impact monitoring** of heavy dependencies
- **Disk usage tracking** with cleanup recommendations
- **Crash reporting** with dependency version information

## Risk Mitigation

### Technical Risks
- **Audio latency issues**: Mitigate through extensive testing and optimization
- **Cross-platform compatibility**: Early testing on all target platforms
- **Performance degradation**: Profiling and optimization throughout development
- **Data migration**: Comprehensive backup and conversion tools
- **Dependency installation failures**: Comprehensive fallback strategies and offline options

### User Experience Risks
- **Feature overwhelming**: Progressive disclosure and guided setup
- **Learning curve**: Extensive help system and tutorials
- **Workflow disruption**: Maintain CLI compatibility during transition
- **Accessibility regression**: WCAG compliance testing throughout development
- **Installation complexity**: Smart installer with automatic platform detection and graceful fallbacks

## Future Enhancements

### Version 2.1 Planned Features
- **Cloud synchronization** for models and recordings
- **Collaborative features** for sharing and improving models
- **Mobile companion app** for remote configuration
- **Plugin ecosystem** for community extensions

### Long-term Vision
- **AI-assisted model optimization** for automatic parameter tuning
- **Real-time collaboration** for multi-user training sessions
- **Advanced audio processing** with noise reduction and enhancement
- **Integration marketplace** for third-party applications and games

---

**Document Version:** 1.0
**Last Updated:** August 25, 2025
**Author:** Development Team
**Stakeholders:** Accessibility Community, Gaming Community, ML Researchers
**Next Review:** September 15, 2025
