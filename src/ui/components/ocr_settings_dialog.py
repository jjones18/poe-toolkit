from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QSlider, QDoubleSpinBox, QComboBox, QCheckBox, 
    QDialogButtonBox, QWidget, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal

class OCRSettingsDialog(QDialog):
    """Dialog for tuning OCR settings in real-time."""
    
    settings_changed = pyqtSignal(dict)  # Emits full settings dict
    
    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR Settings (Real-time)")
        self.setMinimumWidth(400)
        self.settings = current_settings.copy()
        
        layout = QVBoxLayout(self)
        
        # --- Preprocessing Group ---
        prep_group = QGroupBox("Preprocessing")
        prep_layout = QVBoxLayout()
        
        # Scale Factor
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale Factor:"))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(1.0, 5.0)
        self.scale_spin.setSingleStep(0.5)
        self.scale_spin.setValue(self.settings.get('scale_factor', 3.0))
        self.scale_spin.valueChanged.connect(self._on_change)
        scale_layout.addWidget(self.scale_spin)
        prep_layout.addLayout(scale_layout)
        
        # Threshold (Fallback)
        thresh_layout = QVBoxLayout()
        thresh_header = QHBoxLayout()
        thresh_header.addWidget(QLabel("Binary Threshold (Fallback):"))
        self.thresh_val_label = QLabel(str(self.settings.get('threshold', 150)))
        thresh_header.addWidget(self.thresh_val_label)
        thresh_layout.addLayout(thresh_header)
        
        self.thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(0, 255)
        self.thresh_slider.setValue(self.settings.get('threshold', 150))
        self.thresh_slider.valueChanged.connect(self._on_thresh_change)
        thresh_layout.addWidget(self.thresh_slider)
        prep_layout.addLayout(thresh_layout)
        
        # Invert
        self.invert_check = QCheckBox("Invert Image (Light text on Dark bg)")
        self.invert_check.setChecked(self.settings.get('invert', True))
        self.invert_check.stateChanged.connect(self._on_change)
        prep_layout.addWidget(self.invert_check)
        
        prep_group.setLayout(prep_layout)
        layout.addWidget(prep_group)
        
        # --- Tesseract Group ---
        tess_group = QGroupBox("Tesseract Engine")
        tess_layout = QVBoxLayout()
        
        # PSM
        psm_layout = QHBoxLayout()
        psm_layout.addWidget(QLabel("Page Segmentation Mode (PSM):"))
        self.psm_combo = QComboBox()
        self.psm_map = {
            "Auto (Strategies)": 0,
            "3 - Fully automatic": 3,
            "4 - Single column": 4,
            "6 - Single uniform block": 6,
            "7 - Single text line": 7,
            "11 - Sparse text": 11,
            "13 - Raw line": 13
        }
        for name, val in self.psm_map.items():
            self.psm_combo.addItem(name, val)
            
        current_psm = self.settings.get('psm', 0)
        index = self.psm_combo.findData(current_psm)
        if index >= 0:
            self.psm_combo.setCurrentIndex(index)
        self.psm_combo.currentIndexChanged.connect(self._on_change)
        psm_layout.addWidget(self.psm_combo)
        tess_layout.addLayout(psm_layout)
        
        tess_group.setLayout(tess_layout)
        layout.addWidget(tess_group)
        
        # --- Live Preview Group ---
        preview_group = QGroupBox("Live Output")
        preview_layout = QVBoxLayout()
        
        self.raw_text_label = QLabel("Raw: <waiting>")
        self.raw_text_label.setStyleSheet("font-family: Consolas; color: #aaa;")
        self.raw_text_label.setWordWrap(True)
        preview_layout.addWidget(self.raw_text_label)
        
        self.match_label = QLabel("Match: <waiting>")
        self.match_label.setStyleSheet("font-family: Consolas; color: #4fc3f7; font-weight: bold;")
        preview_layout.addWidget(self.match_label)
        
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept) # Close is essentially accept since changes are live
        layout.addWidget(buttons)
        
    def update_preview(self, raw_text: str, matched_tab: str):
        """Update the live preview labels."""
        self.raw_text_label.setText(f"Raw: '{raw_text}'")
        if matched_tab:
            self.match_label.setText(f"Match: {matched_tab}")
            self.match_label.setStyleSheet("font-family: Consolas; color: #00ff00; font-weight: bold;")
        else:
            self.match_label.setText("Match: <none>")
            self.match_label.setStyleSheet("font-family: Consolas; color: #ff4444; font-weight: bold;")

    def _on_thresh_change(self, value):
        self.thresh_val_label.setText(str(value))
        self._on_change()

    def _on_change(self):
        self.settings['threshold'] = self.thresh_slider.value()
        self.settings['scale_factor'] = self.scale_spin.value()
        self.settings['invert'] = self.invert_check.isChecked()
        self.settings['psm'] = self.psm_combo.currentData()
        
        self.settings_changed.emit(self.settings)
