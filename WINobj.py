import sys, json, ctypes, subprocess, os, time, webbrowser
from pathlib import Path
import numpy as np
from PIL import Image

import trimesh
import moderngl
from PySide6.QtWidgets import (QApplication, QWidget, QFileDialog, QVBoxLayout, 
                               QHBoxLayout, QLabel, QProgressBar, QSystemTrayIcon, 
                               QMenu, QDialog, QSlider, QLineEdit, QCheckBox, 
                               QPushButton, QScrollArea, QFormLayout, QFrame, 
                               QMessageBox, QGraphicsOpacityEffect)
from PySide6.QtCore import QTimer, Qt, QPropertyAnimation, QRect
from PySide6.QtGui import QImage, QPainter, QColor, QIcon, QPixmap, QPen

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

APPDATA_DIR = Path(os.getenv('APPDATA')) / "WINobj"
APPDATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = APPDATA_DIR / "config.json"
DATA_PATH = APPDATA_DIR / "data.json"

# ================= 顶部进度条 =================
class SplashWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        screen = QApplication.primaryScreen().size()
        w = screen.width() // 3
        h = 60
        self.setGeometry((screen.width() - w) // 2, h // 2, w, h)
        self.bg_color = QColor(30, 30, 30, 230)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        
        self.label = QLabel("正在启动 WINobj...", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #e0e0e0; font-size: 13px; font-family: 'Microsoft YaHei';")
        
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar { border: none; border-radius: 3px; background-color: #444; }
            QProgressBar::chunk { border-radius: 3px; background-color: #00bfff; }
        """)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.bg_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)

    def set_status(self, percent, text):
        self.progress.setValue(percent)
        self.label.setText(text)
        QApplication.processEvents()

# ================= 顶部悬浮提示框 =================
class ToastWindow(QWidget):
    _instances = []
    
    def __init__(self, message, duration=1000):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        screen = QApplication.primaryScreen().size()
        w = screen.width() // 3
        h = 50
        self.setGeometry((screen.width() - w) // 2, 20, w, h)
        
        layout = QVBoxLayout(self)
        label = QLabel(message, self)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: white; font-size: 13px; font-family: 'Microsoft YaHei';")
        layout.addWidget(label)
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fade_out)
        self.timer.start(duration)
        
        ToastWindow._instances.append(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(40, 40, 40, 240))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)

    def fade_out(self):
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(500)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.close)
        self.anim.start()

    def closeEvent(self, event):
        if self in ToastWindow._instances:
            ToastWindow._instances.remove(self)
        super().closeEvent(event)

# ================= 弹窗 =================
class MissingModelDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("提示")
        self.setFixedSize(320, 150)
        self.setStyleSheet("QDialog { background-color: #2b2b2b; } QLabel { color: #e0e0e0; font-family: 'Microsoft YaHei'; font-size: 13px; }")
        
        layout = QVBoxLayout(self)
        label = QLabel("未读取到模型文件路径，\n请选择您的模型文件", self)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        
        btn_layout = QHBoxLayout()
        btn_choose = QPushButton("选择")
        btn_close = QPushButton("关闭")
        
        btn_choose.setStyleSheet("QPushButton { background-color: #00bfff; color: black; padding: 6px; border-radius: 4px; }")
        btn_close.setStyleSheet("QPushButton { background-color: #555; color: white; padding: 6px; border-radius: 4px; }")
        
        btn_choose.clicked.connect(self.accept)
        btn_close.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_choose)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

class AskTextureDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("提示")
        self.setFixedSize(340, 150)
        self.setStyleSheet("QDialog { background-color: #2b2b2b; } QLabel { color: #e0e0e0; font-family: 'Microsoft YaHei'; font-size: 13px; }")
        
        layout = QVBoxLayout(self)
        label = QLabel("未检测到模型自带的 .mtl 材质文件。\n是否手动选择一张纹理贴图？", self)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        
        btn_layout = QHBoxLayout()
        btn_choose = QPushButton("选择图片")
        btn_close = QPushButton("使用纯色")
        
        btn_choose.setStyleSheet("QPushButton { background-color: #00bfff; color: black; padding: 6px; border-radius: 4px; }")
        btn_close.setStyleSheet("QPushButton { background-color: #555; color: white; padding: 6px; border-radius: 4px; }")
        
        btn_choose.clicked.connect(self.accept)
        btn_close.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_choose)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

# ================= 配置面板 =================
DEFAULT_CONFIG = {
    "gravity": 2500.0, "restitution": 0.3, "friction": 0.8,
    "air_drag": 0.985, "throw_multiplier": 60.0, "max_speed": 5000.0,
    "model_scale": 1.0, "target_height_ratio": 0.2,
    "flip_texture": True, "ambient_light": 0.65, "gamma": 1.2, "audio_volume": 650
}

CONFIG_META = {
    "gravity": {"name": "重力加速度", "min": 0, "max": 10000, "step": 100, "type": "float"},
    "restitution": {"name": "弹性系数", "min": 0, "max": 1, "step": 1, "type": "float", "scale": 100},
    "friction": {"name": "地面摩擦", "min": 0, "max": 1, "step": 1, "type": "float", "scale": 100},
    "air_drag": {"name": "空气阻力", "min": 0.5, "max": 1, "step": 1, "type": "float", "scale": 1000},
    "throw_multiplier": {"name": "甩出力度倍率", "min": 0, "max": 200, "step": 1, "type": "float"},
    "max_speed": {"name": "最大移动速度", "min": 500, "max": 10000, "step": 100, "type": "float"},
    "model_scale": {"name": "模型缩放倍数", "min": 0.1, "max": 5.0, "step": 1, "type": "float", "scale": 100},
    "target_height_ratio": {"name": "模型高度比例", "min": 0.1, "max": 1.0, "step": 1, "type": "float", "scale": 100},
    "flip_texture": {"name": "纹理扭曲修正", "type": "bool"},
    "ambient_light": {"name": "自发光/环境光", "min": 0, "max": 1, "step": 1, "type": "float", "scale": 100},
    "gamma": {"name": "伽马校正", "min": 0.5, "max": 3.0, "step": 1, "type": "float", "scale": 100},
    "audio_volume": {"name": "音频音量", "min": 0, "max": 1000, "step": 10, "type": "float"}
}

class ConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WINobj 配置面板")
        self.setFixedSize(420, 650)
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; }
            QLabel { color: #e0e0e0; font-family: 'Microsoft YaHei'; font-size: 12px; }
            QLineEdit { background-color: #3c3f41; color: #ffffff; border: 1px solid #555; padding: 4px; border-radius: 4px; }
            QCheckBox { color: #e0e0e0; }
        """)
        
        self.widgets = {}
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        param_frame = QFrame()
        param_frame.setStyleSheet("QFrame { background-color: #1e1e1e; border-radius: 6px; }")
        param_layout = QVBoxLayout(param_frame)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        form = QFormLayout(content)
        form.setSpacing(10)
        
        for key, meta in CONFIG_META.items():
            val = cfg.get(key, DEFAULT_CONFIG[key])
            name = meta["name"]
            if meta["type"] == "bool":
                chk = QCheckBox(content)
                chk.setChecked(bool(val))
                self.widgets[key] = chk
                form.addRow(QLabel(name), chk)
            else:
                row = QWidget()
                row.setStyleSheet("background: transparent;")
                h_lay = QHBoxLayout(row)
                h_lay.setContentsMargins(0, 0, 0, 0)
                
                slider = QSlider(Qt.Horizontal)
                slider.setStyleSheet("QSlider::groove:horizontal { height: 6px; background: #444; border-radius: 3px; } QSlider::handle:horizontal { background: #00bfff; width: 14px; margin: -4px 0; border-radius: 7px; } QSlider::sub-page:horizontal { background: #00bfff; border-radius: 3px; }")
                
                line = QLineEdit()
                line.setFixedWidth(60)
                line.setAlignment(Qt.AlignCenter)
                
                scale = meta.get("scale", 1.0)
                slider.setRange(int(meta["min"] * scale), int(meta["max"] * scale))
                slider.setSingleStep(meta.get("step", 1))
                slider.setPageStep(meta.get("step", 1) * 10)
                slider.setValue(int(val * scale))
                line.setText(str(round(val, 3)))
                
                def sync(sl, ln, sc, v):
                    rv = v / sc
                    ln.setText(str(round(rv, 3)))
                slider.valueChanged.connect(lambda v, s=slider, l=line, sc=scale: sync(s, l, sc, v))
                
                def ln_edit(sl, ln, sc):
                    try:
                        rv = float(ln.text())
                        sl.blockSignals(True)
                        sl.setValue(int(rv * sc))
                        sl.blockSignals(False)
                    except ValueError:
                        pass
                line.editingFinished.connect(lambda s=slider, l=line, sc=scale: ln_edit(s, l, sc))
                
                h_lay.addWidget(slider)
                h_lay.addWidget(line)
                self.widgets[key] = (slider, line)
                form.addRow(QLabel(name), row)
        
        scroll.setWidget(content)
        param_layout.addWidget(scroll)
        
        btn_save_layout = QHBoxLayout()
        btn_default = QPushButton("恢复默认")
        btn_default.setStyleSheet("QPushButton { background-color: #555; color: white; padding: 6px 15px; border-radius: 4px; } QPushButton:hover { background-color: #666; }")
        btn_default.clicked.connect(self.reset_default)
        
        btn_save = QPushButton("保存并应用")
        btn_save.setStyleSheet("QPushButton { background-color: #0078d7; color: white; padding: 6px 15px; border-radius: 4px; font-weight: bold; } QPushButton:hover { background-color: #006abc; }")
        btn_save.clicked.connect(self.save_params)
        
        btn_save_layout.addStretch()
        btn_save_layout.addWidget(btn_default)
        btn_save_layout.addWidget(btn_save)
        param_layout.addLayout(btn_save_layout)
        
        main_layout.addWidget(param_frame)
        main_layout.addSpacing(15)
        
        audio_layout = QHBoxLayout()
        btn_press = QPushButton("选择按下时音效")
        btn_release = QPushButton("选择松开后音效")
        for btn in (btn_press, btn_release):
            btn.setStyleSheet("QPushButton { background-color: #444; color: white; padding: 8px; border-radius: 4px; border: 1px solid #555; } QPushButton:hover { background-color: #555; }")
        
        btn_press.clicked.connect(lambda: self.select_audio("press_sound"))
        btn_release.clicked.connect(lambda: self.select_audio("release_sound"))
        
        audio_layout.addStretch()
        audio_layout.addWidget(btn_press)
        audio_layout.addWidget(btn_release)
        audio_layout.addStretch()
        main_layout.addLayout(audio_layout)
        
        main_layout.addSpacing(15)
        
        model_layout = QHBoxLayout()
        btn_model = QPushButton("选择模型")
        btn_model.setFixedSize(180, 40)
        btn_model.setStyleSheet("QPushButton { background-color: #0078d7; color: white; font-size: 14px; border-radius: 6px; font-weight: bold; } QPushButton:hover { background-color: #006abc; }")
        btn_model.clicked.connect(self.select_model)
        
        model_layout.addStretch()
        model_layout.addWidget(btn_model)
        model_layout.addStretch()
        main_layout.addLayout(model_layout)
        
        main_layout.addStretch()
        
        link_layout = QVBoxLayout()
        link_layout.setSpacing(10)
        
        lbl_clear = QLabel("<a href='#' style='color: #ff5555; text-decoration: underline; font-size: 11px;'>清除应用数据</a>")
        lbl_clear.setAlignment(Qt.AlignCenter)
        lbl_clear.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lbl_clear.linkActivated.connect(self.clear_data)
        
        lbl_support = QLabel("<a href='https://space.bilibili.com/1992976149' style='color: #00bfff; text-decoration: underline; font-size: 11px;'>支持我</a>")
        lbl_support.setAlignment(Qt.AlignCenter)
        lbl_support.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lbl_support.setOpenExternalLinks(True)
        
        link_layout.addWidget(lbl_clear)
        link_layout.addWidget(lbl_support)
        main_layout.addLayout(link_layout)
        
        bottom_layout = QHBoxLayout()
        btn_cancel = QPushButton("关闭")
        btn_cancel.setStyleSheet("QPushButton { background-color: #555; color: white; padding: 6px 15px; border-radius: 4px; } QPushButton:hover { background-color: #666; }")
        btn_cancel.clicked.connect(self.accept)
        bottom_layout.addStretch()
        bottom_layout.addWidget(btn_cancel)
        main_layout.addLayout(bottom_layout)

    def save_params(self):
        global cfg
        try:
            new_cfg = {}
            for key, meta in CONFIG_META.items():
                if meta["type"] == "bool":
                    new_cfg[key] = self.widgets[key].isChecked()
                else:
                    slider, line = self.widgets[key]
                    try:
                        new_cfg[key] = float(line.text())
                    except ValueError:
                        new_cfg[key] = cfg.get(key, DEFAULT_CONFIG[key])
            
            CONFIG_PATH.write_text(json.dumps(new_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            cfg.update(new_cfg)
            
            if self.parent() and hasattr(self.parent(), 'apply_config'):
                self.parent().apply_config()
                
            ToastWindow("已保存物理参数信息", 1000).show()
        except Exception:
            ToastWindow("操作失败", 1000).show()

    def reset_default(self):
        try:
            for key, meta in CONFIG_META.items():
                val = DEFAULT_CONFIG[key]
                if meta["type"] == "bool":
                    self.widgets[key].setChecked(val)
                else:
                    slider, line = self.widgets[key]
                    scale = meta.get("scale", 1.0)
                    slider.setValue(int(val * scale))
                    line.setText(str(round(val, 3)))
            ToastWindow("模型参数已恢复默认", 1000).show()
        except Exception:
            ToastWindow("操作失败", 1000).show()

    def select_audio(self, key):
        global data
        try:
            path, _ = QFileDialog.getOpenFileName(self, "选择音频文件", "", "Audio Files (*.mp3 *.wav)")
            if path:
                data[key] = path.replace("\\", "/")
                DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                ToastWindow("音效路径已保存", 1000).show()
        except Exception:
            ToastWindow("操作失败", 1000).show()

    def select_model(self):
        global data
        try:
            path, _ = QFileDialog.getOpenFileName(self, "选择 .obj 模型", str(Path.home()), "OBJ (*.obj)")
            if path:
                data["model_path"] = path.replace("\\", "/")
                data["custom_texture"] = ""
                
                # 核心修复：强制检测是否需要询问贴图
                if not check_model_has_texture(path):
                    dlg = AskTextureDialog()
                    if dlg.exec() == QDialog.Accepted:
                        tex, _ = QFileDialog.getOpenFileName(self, "选择纹理贴图", str(Path(path).parent), "Image Files (*.png *.jpg *.jpeg *.bmp)")
                        if tex:
                            data["custom_texture"] = tex.replace("\\", "/")
                            
                DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                if self.parent() and hasattr(self.parent(), 'reload_model'):
                    self.parent().reload_model()
                ToastWindow("模型已更换", 1000).show()
        except Exception as e:
            ToastWindow(f"操作失败: {e}", 2000).show()

    def clear_data(self):
        reply = QMessageBox.question(self, "确认", "真的要清除所有应用数据吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                close_all_audio()
                import shutil
                shutil.rmtree(APPDATA_DIR)
                
                self.hide()
                if self.parent() and hasattr(self.parent(), 'hide'):
                    self.parent().hide()
                
                t = ToastWindow("应用数据已删除", 3000)
                t.show()
                QTimer.singleShot(4000, lambda: os._exit(0))
            except Exception:
                ToastWindow("操作失败", 1000).show()

# ================= 模型与贴图加载逻辑 =================
def check_model_has_texture(m_path):
    # 暴力检查法：直接读文件源码看有没有 mtllib，防止 trimesh 生成假贴图
    try:
        if not m_path or not Path(m_path).exists(): 
            return False
            
        with open(m_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read().lower()
            if 'mtllib' not in content:
                return False
                
        m = trimesh.load(m_path, force='mesh', skip_materials=False)
        if isinstance(m, trimesh.Scene):
            m = m.to_mesh()
        if hasattr(m, 'visual') and hasattr(m.visual, 'material'):
            mat = m.visual.material
            if hasattr(mat, 'image') and mat.image is not None:
                # 如果解析出了真实的大图片，才算真正有贴图
                if mat.image.size[0] > 4 and mat.image.size[1] > 4:
                    return True
    except Exception:
        pass
    return False

def build_mesh_data(path, custom_tex_path, current_cfg):
    try:
        m = trimesh.load(path, force='mesh')
    except Exception as e:
        raise RuntimeError(f"模型加载失败，文件可能已损坏。\n\n详细错误：{e}")
        
    if isinstance(m, trimesh.Scene): 
        try:
            m = m.to_mesh()
        except Exception:
            raise RuntimeError("模型包含多个网格且无法合并，请使用其他软件重新导出。")

    if m is None or len(m.vertices) == 0 or len(m.faces) == 0:
        raise RuntimeError("模型中不包含任何有效的顶点或面数据。")

    b = m.bounds
    ext = b[1] - b[0]
    md = max(ext)
    t_size = app.primaryScreen().size().height() * current_cfg["target_height_ratio"]
    a_scale = t_size / md if md > 0 else 1.0
    m.apply_scale(current_cfg["model_scale"] * a_scale)
    
    if m.is_watertight:
        cm = m.center_mass
        inertia_z = max(abs(m.moment_inertia[2, 2]), 1500.0)
    else:
        cm = (m.bounds[0] + m.bounds[1]) / 2.0
        inertia_z = max((m.extents[0]**2 + m.extents[1]**2) / 12.0, 1500.0)
    m.apply_translation(-cm)
    
    try:
        v = m.vertices[m.faces].reshape(-1, 3).astype('f4')
        n = m.vertex_normals[m.faces].reshape(-1, 3).astype('f4')
    except Exception as e:
        raise RuntimeError(f"解析模型顶点失败：{e}")

    if hasattr(m.visual, 'uv') and m.visual.uv is not None:
        us = m.visual.uv.shape
        if us[0] == m.faces.shape[0]:
            uv = m.visual.uv.reshape(-1, 2).astype('f4')
        elif us[0] == m.vertices.shape[0]:
            uv = m.visual.uv[m.faces].reshape(-1, 2).astype('f4')
        else:
            uv = np.zeros((len(v), 2), dtype='f4')
    else:
        uv = np.zeros((len(v), 2), dtype='f4')
        
    tex_img = None
    # 优先使用用户自定义的贴图
    if custom_tex_path and Path(custom_tex_path).exists():
        try:
            tex_img = Image.open(custom_tex_path)
        except Exception:
            pass
            
    if tex_img is None:
        if hasattr(m.visual, 'material') and hasattr(m.visual.material, 'image'):
            img = m.visual.material.image
            if img and img.size[0] > 4: # 排除假贴图
                tex_img = img
                
    return v, n, uv, inertia_z, tex_img

def load_json_safe(path, default_dict):
    if not path.exists():
        path.write_text(json.dumps(default_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        return default_dict.copy()
    try:
        content = path.read_text(encoding="utf-8")
        data_loaded = json.loads(content)
        if not isinstance(data_loaded, dict):
            raise ValueError("Not a dictionary")
        for k, v in default_dict.items():
            if k not in data_loaded:
                data_loaded[k] = v
        return data_loaded
    except Exception:
        path.unlink(missing_ok=True)
        path.write_text(json.dumps(default_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        return default_dict.copy()

# ================= 初始化 =================
splash = SplashWindow()
splash.show()
QApplication.processEvents()

splash.set_status(10, "正在读取配置...")
cfg = load_json_safe(CONFIG_PATH, DEFAULT_CONFIG)
data = load_json_safe(DATA_PATH, {"model_path": "", "custom_texture": "", "press_sound": "", "release_sound": ""})

splash.set_status(20, "正在检查模型文件...")
if not data.get("model_path") or not Path(data["model_path"]).exists():
    splash.hide()
    dialog = MissingModelDialog()
    if dialog.exec() == QDialog.Accepted:
        model_path, _ = QFileDialog.getOpenFileName(None, "选择 .obj 模型", str(Path.home()), "OBJ (*.obj)")
        if model_path:
            data["model_path"] = model_path.replace("\\", "/")
            DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            sys.exit(0)
    else:
        sys.exit(0)
    splash.show()

model_path = data["model_path"]

# 启动时的贴图询问逻辑
if not data.get("custom_texture") or not Path(data["custom_texture"]).exists():
    if not check_model_has_texture(model_path):
        splash.hide()
        tex_dlg = AskTextureDialog()
        if tex_dlg.exec() == QDialog.Accepted:
            tex_path, _ = QFileDialog.getOpenFileName(None, "选择纹理贴图", str(Path(model_path).parent), "Image Files (*.png *.jpg *.jpeg *.bmp)")
            if tex_path:
                data["custom_texture"] = tex_path.replace("\\", "/")
                DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        splash.show()

mci = ctypes.windll.winmm.mciSendStringW

def close_all_audio():
    for i in [1, 2]:
        mci(f'close winobj_{i}', None, 0, 0)

def play_sound(key):
    sound_path = data.get(key)
    if not sound_path or not Path(sound_path).exists(): return
    close_all_audio()
    alias = f"winobj_{1 if key == 'press_sound' else 2}"
    vol = int(cfg.get("audio_volume", 650))
    mci(f'open "{sound_path}" type mpegvideo alias {alias}', None, 0, 0)
    mci(f'setaudio {alias} volume to {vol}', None, 0, 0)
    mci(f'play {alias}', None, 0, 0)

def get_rotation_matrix(wx, wy, wz, dt):
    w = np.array([wx, wy, wz])
    w_len = np.linalg.norm(w)
    if w_len < 1e-6: return np.eye(3, dtype='f4')
    axis = w / w_len
    angle = w_len * dt
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    C = 1 - c
    return np.array([
        [x*x*C + c,   x*y*C - z*s, x*z*C + y*s],
        [y*x*C + z*s, y*y*C + c,   y*z*C - x*s],
        [z*x*C - y*s, z*y*C + x*s, z*z*C + c]
    ], dtype='f4')

splash.set_status(40, "正在加载 3D 模型...")

try:
    verts, normals, tex_uv, Iz, tex_image = build_mesh_data(model_path, data.get("custom_texture", ""), cfg)
except Exception as e:
    splash.hide()
    QMessageBox.critical(None, "模型加载失败", str(e))
    sys.exit(1)

screen = app.primaryScreen().size()
W = screen.width()
H = screen.height()

ctx = moderngl.create_standalone_context()
fbo_tex = ctx.texture((W, H), 4)
fbo_depth = ctx.depth_texture((W, H))
fbo = ctx.framebuffer(color_attachments=[fbo_tex], depth_attachment=fbo_depth)

prog = ctx.program(
    vertex_shader='''
#version 330
uniform mat4 mvp; uniform mat4 model;
in vec3 in_pos; in vec3 in_normal; in vec2 in_uv;
out vec3 v_normal; out vec2 v_uv;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_normal = mat3(model) * in_normal;
    v_uv = in_uv;
}''',
    fragment_shader='''
#version 330
in vec3 v_normal; in vec2 v_uv;
uniform vec3 light_dir; uniform sampler2D tex; uniform float has_tex; uniform float ambient_light; uniform float gamma;
out vec4 f_color;
void main() {
    vec4 c = (has_tex > 0.5) ? texture(tex, v_uv) : vec4(0.7, 0.8, 1.0, 1.0);
    if (c.a < 0.2) discard;
    vec3 n = normalize(v_normal);
    float d = max(dot(n, normalize(light_dir)), 0.0);
    vec3 lighting = vec3(ambient_light) + vec3(d * (1.0 - ambient_light));
    f_color = vec4(pow(c.rgb * lighting, vec3(1.0 / gamma)), c.a);
}''')

vbo_pos = ctx.buffer(verts.tobytes())
vbo_nrm = ctx.buffer(normals.tobytes())
vbo_uv = ctx.buffer(tex_uv.tobytes())
vao = ctx.vertex_array(prog, [(vbo_pos, '3f', 'in_pos'), (vbo_nrm, '3f', 'in_normal'), (vbo_uv, '2f', 'in_uv')])

splash.set_status(80, "正在加载纹理...")
tex = None
if tex_image is not None:
    try:
        img = tex_image.convert('RGBA')
        img_data = np.array(img, dtype=np.uint8)
        if cfg.get("flip_texture", True): img_data = np.flipud(img_data)
        tw, th = img.size
        tex = ctx.texture((tw, th), 4, img_data.tobytes())
        tex.repeat_x = tex.repeat_y = False
        tex.build_mipmaps(); tex.use(0)
        prog['tex'] = 0; prog['has_tex'] = 1.0
    except Exception:
        tex = None
        prog['has_tex'] = 0.0
else:
    prog['has_tex'] = 0.0

prog['light_dir'] = (0.3, -0.5, 1.0)
prog['ambient_light'] = float(cfg["ambient_light"])
prog['gamma'] = float(cfg["gamma"])

# ================= 桌宠主体 =================
class Pet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(0, 0, W, H)
        self.setFocusPolicy(Qt.StrongFocus)
        
        self.cx, self.cy = float(W / 2), float(H / 2)
        self.vx = self.vy = 0.0
        self.rot_mat = np.eye(3, dtype='f4')
        self.wx = self.wy = self.wz = 0.0
        
        self.dragging = False
        self.local_click = np.zeros(3, dtype='f4') 
        self.mouse_pos = (0, 0)
        self.last_mouse_pos = None
        self.keys_pressed = set()
        self._img = self._img_rect = None
        self.config_dialog = None
        
        self._last_geom_cfg = (cfg["model_scale"], cfg["target_height_ratio"], cfg["flip_texture"])
        
        self.setup_tray()
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(128, 128)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(135, 206, 250)); pen.setWidth(12)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 192, 203))
        painter.drawEllipse(10, 10, 108, 108)
        painter.end()
        
        app_icon = QIcon(pixmap)
        self.setWindowIcon(app_icon)
        self.tray_icon.setIcon(app_icon)
        self.tray_icon.setToolTip("WINobj 桌宠")
        
        menu = QMenu()
        menu.setStyleSheet("QMenu { background-color: #2b2b2b; color: white; border: 1px solid #555; } QMenu::item:selected { background-color: #00bfff; color: black; }")
        action_config = menu.addAction("配置文件")
        action_quit = menu.addAction("退出")
        action_config.triggered.connect(self.open_config)
        action_quit.triggered.connect(self.exit_app)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(lambda r: self.open_config() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray_icon.show()

    def open_config(self):
        if not self.config_dialog or not self.config_dialog.isVisible():
            self.config_dialog = ConfigDialog(self)
            self.config_dialog.show()
        else:
            self.config_dialog.raise_()
            self.config_dialog.activateWindow()

    def exit_app(self):
        close_all_audio()
        self.tray_icon.hide()
        os._exit(0)

    def apply_config(self):
        global verts, normals, tex_uv, Iz, tex
        
        current_geom_cfg = (cfg["model_scale"], cfg["target_height_ratio"], cfg["flip_texture"])
        if self._last_geom_cfg != current_geom_cfg:
            try:
                verts, normals, tex_uv, Iz, tex_image = build_mesh_data(model_path, data.get("custom_texture", ""), cfg)
            except Exception as e:
                ToastWindow(f"模型重载失败: {e}", 2000).show()
                return
                
            vbo_pos.write(verts.tobytes())
            vbo_nrm.write(normals.tobytes())
            vbo_uv.write(tex_uv.tobytes())
            
            if tex_image is not None:
                try:
                    img = tex_image.convert('RGBA')
                    img_data = np.array(img, dtype=np.uint8)
                    if cfg.get("flip_texture", True): img_data = np.flipud(img_data)
                    tw, th = img.size
                    if tex: tex.release()
                    tex = ctx.texture((tw, th), 4, img_data.tobytes())
                    tex.repeat_x = tex.repeat_y = False
                    tex.build_mipmaps(); tex.use(0)
                    prog['tex'] = 0; prog['has_tex'] = 1.0
                except Exception:
                    if tex: tex.release()
                    tex = None
                    prog['has_tex'] = 0.0
            else:
                if tex: tex.release()
                tex = None
                prog['has_tex'] = 0.0
                
            self._last_geom_cfg = current_geom_cfg
            
            self.cx, self.cy = float(W/2), float(H/2)
            self.vx = self.vy = 0.0
            self.wx = self.wy = self.wz = 0.0
            self.rot_mat = np.eye(3, dtype='f4')
            
        prog['ambient_light'] = float(cfg["ambient_light"])
        prog['gamma'] = float(cfg["gamma"])

    def reload_model(self):
        global verts, normals, tex_uv, Iz, tex, model_path
        
        model_path = data["model_path"]
        try:
            verts, normals, tex_uv, Iz, tex_image = build_mesh_data(model_path, data.get("custom_texture", ""), cfg)
        except Exception as e:
            ToastWindow(f"模型加载失败: {e}", 3000).show()
            return
        
        vbo_pos.write(verts.tobytes())
        vbo_nrm.write(normals.tobytes())
        vbo_uv.write(tex_uv.tobytes())
        
        if tex_image is not None:
            try:
                img = tex_image.convert('RGBA')
                img_data = np.array(img, dtype=np.uint8)
                if cfg.get("flip_texture", True): img_data = np.flipud(img_data)
                tw, th = img.size
                if tex: tex.release()
                tex = ctx.texture((tw, th), 4, img_data.tobytes())
                tex.repeat_x = tex.repeat_y = False
                tex.build_mipmaps(); tex.use(0)
                prog['tex'] = 0; prog['has_tex'] = 1.0
            except Exception:
                if tex: tex.release()
                tex = None
                prog['has_tex'] = 0.0
        else:
            if tex: tex.release()
            tex = None
            prog['has_tex'] = 0.0
            
        self._last_geom_cfg = (cfg["model_scale"], cfg["target_height_ratio"], cfg["flip_texture"])
        
        self.cx, self.cy = float(W/2), float(H/2)
        self.vx = self.vy = 0.0
        self.wx = self.wy = self.wz = 0.0
        self.rot_mat = np.eye(3, dtype='f4')

    def resolve_collision(self, cx, cy, nx, ny):
        rx, ry = cx - self.cx, cy - self.cy
        vp_x, vp_y = self.vx - self.wz * ry, self.vy + self.wz * rx
        vn = vp_x * nx + vp_y * ny
        inv_I = 1.0 / Iz
        if vn < 0:
            r_n = rx * ny - ry * nx
            Jn = -(1.0 + cfg["restitution"]) * vn / (1.0 + (r_n ** 2) * inv_I)
            self.vx += Jn * nx; self.vy += Jn * ny
            self.wz += (rx * (Jn * ny) - ry * (Jn * nx)) * inv_I
            
            vp_x, vp_y = self.vx - self.wz * ry, self.vy + self.wz * rx
            vt = vp_x * -ny + vp_y * nx
            r_t = rx * nx + ry * ny
            Jt = np.clip(-vt / (1.0 + (r_t ** 2) * inv_I), -cfg["friction"] * abs(Jn), cfg["friction"] * abs(Jn))
            self.vx += Jt * -ny; self.vy += Jt * nx
            self.wz += (rx * (Jt * nx) - ry * (Jt * -ny)) * inv_I

    def tick(self):
        dt = 1.0 / 60.0
        if self.dragging and self.last_mouse_pos:
            mx, my = self.mouse_pos[0], H - self.mouse_pos[1]
            mx_vel = (self.mouse_pos[0] - self.last_mouse_pos[0]) / dt
            my_vel = ((H - self.mouse_pos[1]) - (H - self.last_mouse_pos[1])) / dt
            rx, ry = mx - self.cx, my - self.cy
            
            rot_speed = 3.0
            self.wy = -rot_speed if Qt.Key_A in self.keys_pressed else rot_speed if Qt.Key_D in self.keys_pressed else self.wy * 0.85
            self.wx = -rot_speed if Qt.Key_W in self.keys_pressed else rot_speed if Qt.Key_S in self.keys_pressed else self.wx * 0.85
            if Qt.Key_Q in self.keys_pressed: self.wz = -rot_speed
            elif Qt.Key_E in self.keys_pressed: self.wz = rot_speed
            else: 
                target_wz = (rx * my_vel - ry * mx_vel) / Iz * 30.0 + (self.rot_mat @ self.local_click)[0] * cfg["gravity"] / Iz * 2.0
                self.wz = self.wz * 0.85 + target_wz * 0.15 if abs(target_wz) >= 0.5 or (mx_vel**2 + my_vel**2) >= 10 else 0.0
            
            if abs(self.wx) > 0.01 or abs(self.wy) > 0.01 or abs(self.wz) > 0.01:
                self.rot_mat = get_rotation_matrix(self.wx, self.wy, self.wz, dt) @ self.rot_mat
            
            click_world = self.rot_mat @ self.local_click
            self.cx, self.cy = mx - click_world[0], my - click_world[1]
            self.vx = self.vy = 0.0
        else:
            self.vy -= cfg["gravity"] * dt
            self.vx *= cfg["air_drag"]; self.vy *= cfg["air_drag"]
            self.wx *= cfg["air_drag"]; self.wy *= cfg["air_drag"]; self.wz *= cfg["air_drag"]
            self.cx += self.vx * dt; self.cy += self.vy * dt
            
            if abs(self.wx) > 0.01 or abs(self.wy) > 0.01 or abs(self.wz) > 0.01:
                self.rot_mat = get_rotation_matrix(self.wx, self.wy, self.wz, dt) @ self.rot_mat
                
            world_v = verts @ self.rot_mat.T + np.array([self.cx, self.cy, 0], dtype='f4')
            min_x, max_x = float(world_v[:, 0].min()), float(world_v[:, 0].max())
            min_y, max_y = float(world_v[:, 1].min()), float(world_v[:, 1].max())
            
            if min_y < 0:
                self.cy -= min_y
                self.resolve_collision(np.mean(world_v[world_v[:, 1] <= min_y + 2.0][:, 0]), min_y, 0.0, 1.0)
            elif max_y > H:
                self.cy -= (max_y - H)
                self.resolve_collision(np.mean(world_v[world_v[:, 1] >= max_y - 2.0][:, 0]), max_y, 0.0, -1.0)
            if min_x < 0:
                self.cx -= min_x
                self.resolve_collision(min_x, np.mean(world_v[world_v[:, 0] <= min_x + 2.0][:, 1]), 1.0, 0.0)
            elif max_x > W:
                self.cx -= (max_x - W)
                self.resolve_collision(max_x, np.mean(world_v[world_v[:, 0] >= max_x - 2.0][:, 1]), -1.0, 0.0)

            if min_y < 10.0 and abs(self.vy) < 50:
                self.vx *= 0.85; self.wz *= 0.85
                if abs(self.vx) < 3.0 and abs(self.wz) < 0.05:
                    self.vx = self.wz = 0.0
                    self.wx *= 0.5; self.wy *= 0.5

        m = np.eye(4, dtype='f4')
        m[:3, :3] = self.rot_mat
        m[:3, 3] = [self.cx, self.cy, 0]
        
        world_v_r = verts @ self.rot_mat.T + np.array([self.cx, self.cy, 0], dtype='f4')
        vx = max(0, int(float(world_v_r[:, 0].min())) - 8)
        vy = max(0, int(float(world_v_r[:, 1].min())) - 8)
        vw = min(W - vx, int(float(world_v_r[:, 0].max()) - float(world_v_r[:, 0].min())) + 16)
        vh = min(H - vy, int(float(world_v_r[:, 1].max()) - float(world_v_r[:, 1].min())) + 16)
        if vw <= 0 or vh <= 0: return

        proj = np.array([[2.0/W, 0, 0, -1], [0, 2.0/H, 0, -1], [0, 0, 0.001, 0], [0, 0, 0, 1]], dtype='f4')
        mvp = proj @ m

        fbo.use()
        ctx.viewport = (0, 0, W, H)
        ctx.clear(0, 0, 0, 0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.disable(moderngl.CULL_FACE)
        
        prog['mvp'].write(np.ascontiguousarray(mvp.T, dtype='f4').tobytes())
        prog['model'].write(np.ascontiguousarray(m.T, dtype='f4').tobytes())
        vao.render(vertices=len(verts))

        data_pixels = fbo.read(components=4, viewport=(vx, vy, vw, vh))
        img = QImage(bytearray(data_pixels), vw, vh, vw * 4, QImage.Format_RGBA8888).mirrored(False, True).copy()

        self._img = img
        self._img_rect = (vx, H - (vy + vh), vw, vh)
        self.update()

    def paintEvent(self, e):
        qp = QPainter(self)
        qp.setCompositionMode(QPainter.CompositionMode_Source)
        qp.fillRect(self.rect(), Qt.transparent)
        qp.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self._img and self._img_rect:
            x, y, w, h = self._img_rect
            qp.drawImage(x, y, self._img)
        qp.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._img_rect:
            x, y, w, h = self._img_rect
            if x - 10 <= e.position().x() <= x + w + 10 and y - 10 <= e.position().y() <= y + h + 10:
                self.activateWindow(); self.setFocus()
                self.dragging = True
                self.mouse_pos = (e.position().x(), e.position().y())
                self.last_mouse_pos = self.mouse_pos
                self.local_click = self.rot_mat.T @ np.array([self.mouse_pos[0] - self.cx, H - self.mouse_pos[1] - self.cy, 0], dtype='f4')
                play_sound("press_sound")

    def mouseMoveEvent(self, e):
        self.last_mouse_pos = self.mouse_pos
        self.mouse_pos = (e.position().x(), e.position().y())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            play_sound("release_sound")
            if self.last_mouse_pos and self.mouse_pos:
                dx, dy = self.mouse_pos[0] - self.last_mouse_pos[0], self.mouse_pos[1] - self.last_mouse_pos[1]
                self.vx, self.vy = dx * cfg["throw_multiplier"], -dy * cfg["throw_multiplier"]
                self.wy += self.vx * 0.005
                self.wx += -self.vy * 0.005

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape: self.exit_app()
        elif e.key() in (Qt.Key_A, Qt.Key_D, Qt.Key_W, Qt.Key_S, Qt.Key_Q, Qt.Key_E): self.keys_pressed.add(e.key())
        else: super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() in self.keys_pressed: self.keys_pressed.remove(e.key())
        else: super().keyReleaseEvent(e)

splash.set_status(100, "准备就绪！")
time.sleep(0.2)
win = Pet()
win.show()
splash.close()
sys.exit(app.exec())
