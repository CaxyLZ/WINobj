import sys, json, ctypes, subprocess, os, time, webbrowser, zipfile, hashlib, shutil
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
MODEL_CACHE_DIR = APPDATA_DIR / "model_cache"

# 支持的模型格式（.zip 用来直接吃 Sketchfab 的下载压缩包）
SUPPORTED_MODEL_EXTS = (".obj", ".glb", ".gltf", ".usdz", ".usd", ".usda", ".usdc")
MODEL_FILE_FILTER = ("3D 模型 (*.obj *.glb *.gltf *.usdz *.zip *.usd *.usda *.usdc);;"
                     "Wavefront OBJ (*.obj);;"
                     "glTF 2.0 (*.glb *.gltf);;"
                     "USD / USDZ (*.usdz *.usd *.usda *.usdc);;"
                     "Sketchfab 压缩包 (*.zip);;"
                     "所有文件（扩展名被改过也能读） (*.*)")

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
        label = QLabel("未检测到模型自带的贴图\n（.mtl 材质或内嵌纹理）。\n是否手动选择一张纹理贴图？", self)
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
            path, _ = QFileDialog.getOpenFileName(self, "选择模型文件", str(Path.home()), MODEL_FILE_FILTER)
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
# .obj / .glb / .gltf 交给 trimesh（glTF 是它原生支持的，不需要额外依赖），
# .usdz 交给可选的 usd-core（Pixar 官方 OpenUSD 解析器），.zip 用来直接吃 Sketchfab 的下载包。
# 扩展名不可信（下载工具会改名），所以真正的格式按文件头认。
_ZIP_MODEL_PRIORITY = (".glb", ".gltf", ".usdz", ".obj")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga")

_MODEL_LOAD_CACHE = {"key": None, "mesh": None}


def _zip_kind(path):
    """PK 开头的既可能是 zip 也可能是 usdz（USDZ 本质就是 zip），看里面有没有 USD 场景。"""
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n.lower() for n in zf.namelist()]
    except Exception:
        return ".zip"
    if any(n.endswith((".usd", ".usda", ".usdc")) for n in names):
        return ".usdz"
    return ".zip"


def sniff_model_ext(path):
    """按文件头判断真实格式，别被扩展名骗了（.circ / .bin / 无扩展名都可能藏着模型）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except Exception:
        return Path(path).suffix.lower()

    if head[:4] == b"glTF":
        return ".glb"
    if head[:2] == b"PK":
        return _zip_kind(path)
    if head[:8] == b"PXR-USDC":
        return ".usdc"          # 二进制 crate
    if head[:5] in (b"#usda", b"#usdc"):
        return ".usda"          # 文本版 USD
    stripped = head.lstrip()
    if stripped[:3].lower() == b"ply":
        return ".ply"
    if stripped[:1] in (b"{", b"<"):
        # glTF 的 JSON 版，或者别的文本格式
        text = head.decode("utf-8", "ignore")
        if '"asset"' in text and ('"meshes"' in text or '"buffers"' in text or '"scenes"' in text):
            return ".gltf"
        return Path(path).suffix.lower()
    # OBJ 是纯文本：有 v 行，也有 f / vn / mtllib 之类的行
    lines = [ln.strip() for ln in head.decode("utf-8", "ignore").splitlines()[:500]]
    if any(ln.startswith(("v ", "v\t")) for ln in lines) and \
            any(ln.startswith(("f ", "vn ", "mtllib", "usemtl", "o ", "g ")) for ln in lines):
        return ".obj"
    return Path(path).suffix.lower()


def _cache_slot(path):
    """按 路径+大小+修改时间 生成缓存目录名，换模型就会换目录。"""
    try:
        st = Path(path).stat()
        raw = f"{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}"
    except Exception:
        raw = str(path)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]


def reset_model_cache_dir(keep=None):
    """清掉上一轮解包出来的临时文件（keep 传目录名时保留那一份）。"""
    try:
        if not MODEL_CACHE_DIR.exists():
            return
        for item in MODEL_CACHE_DIR.iterdir():
            if keep and item.name == keep:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
    except Exception:
        pass


def _extract_zip(zip_path, dest):
    """把压缩包解到 dest，带路径穿越防护。.usdz 本质上也是 zip，走同一套。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith("__MACOSX/") or "/." in name or name.startswith("."):
                continue
            target = dest / name
            try:
                target.resolve().relative_to(root)
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return dest


def resolve_model_path(path):
    """Sketchfab 的下载包常常是 zip：解开后返回里面真正的模型文件。"""
    p = Path(path)
    if sniff_model_ext(p) != ".zip":
        return p
    dest = MODEL_CACHE_DIR / ("zip_" + _cache_slot(p))
    if not (dest.is_dir() and any(dest.iterdir())):
        shutil.rmtree(dest, ignore_errors=True)
        _extract_zip(p, dest)

    files = [q for q in dest.rglob("*") if q.is_file()]
    candidates = [(q.suffix.lower(), q) for q in files if q.suffix.lower() in _ZIP_MODEL_PRIORITY]
    if not candidates:
        # 包里文件也被改过名：挨个闻文件头（太小的多半是贴图，跳过）
        for q in files:
            try:
                if q.stat().st_size < 1024:
                    continue
            except Exception:
                continue
            ext = sniff_model_ext(q)
            if ext in _ZIP_MODEL_PRIORITY:
                candidates.append((ext, q))
    if not candidates:
        raise RuntimeError("压缩包里没有找到受支持的模型文件。\n支持的类型：.obj / .glb / .gltf / .usdz")
    candidates.sort(key=lambda item: (_ZIP_MODEL_PRIORITY.index(item[0]),
                                      len(item[1].parts), str(item[1]).lower()))
    return candidates[0][1]


def _material_image(mat):
    """取材质贴图。trimesh 5.x 的 PBRMaterial 放在 baseColorTexture，OBJ 的 SimpleMaterial 放在 image。"""
    if mat is None:
        return None
    for attr in ("image", "baseColorTexture", "emissiveTexture"):
        img = getattr(mat, attr, None)
        if isinstance(img, Image.Image) and img.size[0] > 4 and img.size[1] > 4:
            return img
    return None


def _mesh_texture(mesh):
    return _material_image(getattr(getattr(mesh, "visual", None), "material", None))


def compute_vertex_normals(mesh):
    """顶点法线。没装 scipy 时 trimesh 自带实现是纯 Python 循环，几万面的模型要几十秒，
    这里退回 numpy 累加（面积加权），大模型也能立刻算完。"""
    try:
        import scipy  # noqa: F401
        return mesh.vertex_normals
    except Exception:
        pass

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(verts) == 0 or len(faces) == 0:
        return np.zeros_like(verts)
    tri = verts[faces]
    face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])  # 长度 = 2×面积
    normals = np.zeros_like(verts)
    for k in range(3):
        np.add.at(normals, faces[:, k], face_normals)
    length = np.linalg.norm(normals, axis=1)
    good = length > 1e-12
    normals[good] /= length[good, None]
    normals[~good] = (0.0, 0.0, 1.0)  # 退化点给个朝向，别把着色算成 NaN
    return normals


def _scene_to_mesh(scene):
    """把 Scene 压成一整块网格：保留 UV，贴图取面数最多的那份材质。

    不直接用 Scene.to_mesh()，因为它遇到多材质时会烘焙出一张全透明的空贴图（模型会直接看不见）。
    """
    geoms = [g for g in scene.dump()
             if isinstance(g, trimesh.Trimesh) and len(getattr(g, "faces", ())) > 0]
    if not geoms:
        raise RuntimeError("模型里没有可用的三角面片。")
    geoms.sort(key=lambda g: len(g.faces), reverse=True)

    image = None
    for g in geoms:
        image = _mesh_texture(g)
        if image is not None:
            break

    verts, faces, uvs, base = [], [], [], 0
    any_uv = any(getattr(g.visual, "uv", None) is not None for g in geoms)
    for g in geoms:
        verts.append(np.asarray(g.vertices, dtype=np.float64))
        faces.append(np.asarray(g.faces, dtype=np.int64) + base)
        uv = getattr(g.visual, "uv", None)
        if uv is not None and len(uv) == len(g.vertices):
            uvs.append(np.asarray(uv, dtype=np.float64))
        elif any_uv:
            # 个别子网格没有 UV 时补 0，别把整份模型的 UV 都丢掉
            uvs.append(np.zeros((len(g.vertices), 2), dtype=np.float64))
        base += len(g.vertices)

    mesh = trimesh.Trimesh(vertices=np.vstack(verts), faces=np.vstack(faces), process=False)
    if image is not None:
        if any_uv:
            mesh.visual = trimesh.visual.TextureVisuals(uv=np.vstack(uvs), image=image)
        else:
            mesh.visual = trimesh.visual.TextureVisuals(image=image)
    return mesh


def _load_usd_mesh(path):
    """USD 系读成一块带 UV 和贴图的网格。

    两种形态都认：
      · `.usdz` —— USD 场景 + 贴图打成的 zip 包（会自动解包）
      · 裸 `.usd` / `.usda` / `.usdc` —— 散文件，贴图按它所在目录解析
    """
    try:
        from pxr import Usd, UsdGeom, UsdShade, Sdf
    except Exception:
        raise RuntimeError(
            "打开 USD 模型需要一个额外的解析库（Pixar 官方 OpenUSD）。\n\n"
            "请在命令行执行：\n    pip install usd-core\n"
            "装好之后再打开本程序即可。\n\n"
            "（不想装的话，也可以用 Sketchfab 的 .glb 下载，那个不需要额外依赖。）")

    p = Path(path)
    if sniff_model_ext(p) == ".usdz":
        work_dir = MODEL_CACHE_DIR / ("usdz_" + _cache_slot(p))
        shutil.rmtree(work_dir, ignore_errors=True)
        _extract_zip(p, work_dir)
        usd_files = [q for q in work_dir.rglob("*") if q.suffix.lower() in (".usd", ".usda", ".usdc")]
        if not usd_files:
            raise RuntimeError("这个 .usdz 里没有 USD 场景文件，文件可能已损坏。")
        stage = None
        for cand in sorted(usd_files, key=lambda q: q.stat().st_size, reverse=True):
            try:
                st = Usd.Stage.Open(str(cand))
            except Exception:
                continue
            if st is not None and any(prim.IsA(UsdGeom.Mesh) for prim in st.Traverse()):
                stage = st
                break
    else:
        work_dir = p.parent       # 散文件：贴图相对 USD 文件所在目录
        try:
            stage = Usd.Stage.Open(str(p))
        except Exception as e:
            raise RuntimeError(f"USD 文件打不开：{e}")
        if stage is not None and not any(prim.IsA(UsdGeom.Mesh) for prim in stage.Traverse()):
            stage = None
    if stage is None:
        raise RuntimeError("USD 场景里没有找到网格（Mesh）。\n点云、曲线、纯骨骼类资产暂时不支持。")

    try:
        up_axis = str(stage.GetMetadata("upAxis") or "Y").upper()
    except Exception:
        up_axis = "Y"
    # Z-up 的资产转成 Y-up，否则模型会"躺"在桌面上
    up_rot = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=np.float64) \
        if up_axis == "Z" else np.identity(4)

    def _shader_texture_paths(mat):
        """在材质网络里找贴图：优先 diffuse/base color 那一路。"""
        hits = []

        def follow_shader(shader, depth=0):
            if shader is None or depth > 8:
                return
            src = shader.GetInput("file")
            val = src.Get() if src else None
            if isinstance(val, Sdf.AssetPath) and val.path:
                hits.append(val.resolvedPath or str(work_dir / val.path))

        def walk(prim, depth=0):
            if prim is None or depth > 8:
                return
            shader = UsdShade.Shader(prim)
            if shader:
                sid = str(shader.GetIdAttr().Get() or "")
                if sid.startswith("UsdPreviewSurface") or sid == "UsdPrimvarReader_float2":
                    for name in ("diffuseColor", "emissiveColor", "baseColor"):
                        inp = shader.GetInput(name)
                        if inp is None:
                            continue
                        try:
                            connected = inp.GetConnectedSource()
                        except Exception:
                            connected = None
                        if connected:
                            follow_shader(UsdShade.Shader(connected[0]))
                if sid.startswith("UsdUVTexture"):
                    follow_shader(shader)
            for child in prim.GetChildren():
                walk(child, depth + 1)

        walk(mat.GetPrim())
        return hits

    xf_cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    corner_pos, corner_uv, tex_paths = [], [], []

    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        usd_mesh = UsdGeom.Mesh(prim)
        points = usd_mesh.GetPointsAttr().Get()
        counts = usd_mesh.GetFaceVertexCountsAttr().Get()
        indices = usd_mesh.GetFaceVertexIndicesAttr().Get()
        if not points or not counts or not indices:
            continue

        points = np.asarray(points, dtype=np.float64)
        counts = np.asarray(counts, dtype=np.int64)
        indices = np.asarray(indices, dtype=np.int64)
        # 面索引和顶点对不上就跳过这一块，别让整份模型读不出来
        if counts.sum() != len(indices) or indices.size == 0 \
                or int(indices.max()) >= len(points) or int(indices.min()) < 0:
            continue
        try:
            mtx = up_rot @ np.array(xf_cache.GetLocalToWorldTransform(prim), dtype=np.float64)
        except Exception:
            mtx = up_rot
        points = points @ mtx[:3, :3].T + mtx[:3, 3]

        # 多边形面 → 三角面，同时记下每个三角形用的"角"序号（UV 可能按角给）
        tri_corner, start = [], 0
        for c in counts:
            c = int(c)
            if c >= 3:
                for k in range(1, c - 1):
                    tri_corner.append((start, start + k, start + k + 1))
            start += c
        if not tri_corner:
            continue
        tri_corner = np.asarray(tri_corner, dtype=np.int64)
        corner_index = indices[tri_corner]              # 角 -> 顶点
        flat_pos = points[corner_index].reshape(-1, 3)  # 每个角一个位置

        uv = np.zeros((flat_pos.shape[0], 2), dtype=np.float64)
        try:
            primvar = None
            for pv in UsdGeom.PrimvarsAPI(prim).GetPrimvars():
                if str(pv.GetTypeName()).startswith("texCoord2") and pv.HasValue():
                    primvar = pv
                    break
            if primvar is not None:
                vals = np.asarray(primvar.Get(), dtype=np.float64).reshape(-1, 2)
                interp = primvar.GetInterpolation()
                if interp in ("faceVarying", "varying") and len(vals) == len(indices):
                    uv = vals[tri_corner].reshape(-1, 2)
                elif interp == "vertex" and len(vals) == len(points):
                    uv = vals[corner_index].reshape(-1, 2)
                elif interp == "uniform" and len(vals) == len(counts):
                    face_of_corner = np.repeat(np.arange(len(counts)), counts)[tri_corner]
                    uv = vals[face_of_corner].reshape(-1, 2)
                elif interp == "constant" and len(vals) >= 1:
                    uv = np.repeat(vals[:1], flat_pos.shape[0], axis=0)
        except Exception:
            pass

        corner_pos.append(flat_pos)
        corner_uv.append(uv)

        try:
            mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        except Exception:
            mat = None
        if mat:
            for tex in _shader_texture_paths(mat):
                if tex not in tex_paths:
                    tex_paths.append(tex)

    if not corner_pos:
        raise RuntimeError("USD 场景里没有可用的三角面。")

    # 位置 + UV 一起做去重：UV 一致的地方合并顶点，接缝处自动拆开
    keys = np.round(np.hstack([np.vstack(corner_pos), np.vstack(corner_uv)]), 7)
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    mesh = trimesh.Trimesh(vertices=uniq[:, :3], faces=inverse.reshape(-1, 3), process=False)

    image = None
    for tex in tex_paths:
        try:
            img = Image.open(tex)
            img.load()
            if img.size[0] > 4 and img.size[1] > 4:
                image = img
                break
        except Exception:
            continue
    if image is None:
        # 兜底：材质网络认不出来时，用同一目录下最大的那张图
        pics = []
        try:
            for q in work_dir.rglob("*"):
                if q.suffix.lower() in _IMAGE_EXTS:
                    pics.append(q)
                    if len(pics) >= 200:   # 散文件时目录可能很大，别把整盘都扫一遍
                        break
        except Exception:
            pass
        pics.sort(key=lambda q: q.stat().st_size, reverse=True)
        for pic in pics:
            try:
                img = Image.open(pic)
                img.load()
                image = img
                break
            except Exception:
                continue

    if image is not None:
        mesh.visual = trimesh.visual.TextureVisuals(uv=uniq[:, 3:5], image=image)
    return mesh


def load_model_mesh(model_path):
    """把任意受支持的模型读成一块 trimesh.Trimesh（带 UV 和贴图），并按文件缓存。"""
    p = Path(model_path)
    if not p.exists():
        raise RuntimeError(f"找不到模型文件：\n{p}")

    cache_key = (str(p), _cache_slot(p))
    if _MODEL_LOAD_CACHE["key"] == cache_key and _MODEL_LOAD_CACHE["mesh"] is not None:
        return _MODEL_LOAD_CACHE["mesh"]

    real = resolve_model_path(p)
    ext = sniff_model_ext(real)
    if ext not in SUPPORTED_MODEL_EXTS:
        raise RuntimeError(
            f"暂不支持 {ext or '这种'} 格式。\n"
            "支持：.obj / .glb / .gltf / .usdz（或解压后的 .usd/.usdc），也可以直接选 .zip 压缩包。\n"
            "（扩展名改过也没关系，程序是看文件内容认格式的。）")

    try:
        if ext in (".usdz", ".usd", ".usda", ".usdc"):
            mesh = _load_usd_mesh(real)
        else:
            # 必须显式告诉 trimesh 真实格式：它默认只看扩展名，被改过名的文件会认不出来
            loaded = trimesh.load(str(real), file_type=ext.lstrip("."),
                                  force="scene", skip_materials=False)
            if isinstance(loaded, trimesh.Scene):
                mesh = _scene_to_mesh(loaded)
            elif isinstance(loaded, trimesh.Trimesh):
                mesh = loaded
            else:
                raise RuntimeError("读出来的内容不是三角网格。")
    except RuntimeError:
        raise
    except Exception as e:
        hint = ""
        if ext == ".gltf":
            hint = ("\n\n提示：.gltf 依赖同目录的 .bin 和贴图文件。\n"
                    "如果是 Sketchfab 下载的包，直接把整个压缩包交给本程序（选 .zip），或改用 .glb。")
        raise RuntimeError(f"模型加载失败，文件可能已损坏。{hint}\n\n详细错误：{e}")

    # 贴图数据立刻读进内存：之后解包目录被清掉也不影响已经载入的模型
    img = _mesh_texture(mesh)
    if img is not None:
        try:
            img.load()
        except Exception:
            pass

    _MODEL_LOAD_CACHE["key"] = cache_key
    _MODEL_LOAD_CACHE["mesh"] = mesh
    return mesh


def check_model_has_texture(m_path):
    """模型自带贴图吗？.obj 先看有没有 mtllib，其余格式直接读一遍看材质里的图。"""
    try:
        path = Path(m_path)
        if not path.exists():
            return False
        if sniff_model_ext(path) == ".obj":
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                if 'mtllib' not in f.read().lower():
                    return False
        img = _mesh_texture(load_model_mesh(m_path))
        return img is not None and img.size[0] > 4 and img.size[1] > 4
    except Exception:
        pass
    return False

def build_mesh_data(path, custom_tex_path, current_cfg):
    try:
        m = load_model_mesh(path).copy()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"模型加载失败，文件可能已损坏。\n\n详细错误：{e}")

    if isinstance(m, trimesh.Scene):
        try:
            m = _scene_to_mesh(m)
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
        n = compute_vertex_normals(m)[m.faces].reshape(-1, 3).astype('f4')
    except Exception as e:
        raise RuntimeError(f"解析模型顶点失败：{e}")

    if hasattr(m.visual, 'uv') and m.visual.uv is not None:
        us = m.visual.uv.shape
        if us[0] == m.faces.shape[0] * 3:
            uv = m.visual.uv.reshape(-1, 2).astype('f4')
        elif us[0] == m.faces.shape[0]:
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
        tex_img = _mesh_texture(m)
                
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
        model_path, _ = QFileDialog.getOpenFileName(None, "选择模型文件", str(Path.home()), MODEL_FILE_FILTER)
        if model_path:
            data["model_path"] = model_path.replace("\\", "/")
            DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            sys.exit(0)
    else:
        sys.exit(0)
    splash.show()

model_path = data["model_path"]

# 清掉上一轮解包留下的临时文件（换模型时重新解一次就好）
reset_model_cache_dir()

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

def upload_mesh_buffers(new_v, new_n, new_uv):
    """把网格传到显卡。顶点数变了必须重建 buffer 和 vao —— moderngl 的 buffer 不会自动扩容。"""
    global vbo_pos, vbo_nrm, vbo_uv, vao
    if (vbo_pos.size == new_v.nbytes and vbo_nrm.size == new_n.nbytes
            and vbo_uv.size == new_uv.nbytes):
        vbo_pos.write(new_v.tobytes())
        vbo_nrm.write(new_n.tobytes())
        vbo_uv.write(new_uv.tobytes())
        return
    for obj in (vao, vbo_pos, vbo_nrm, vbo_uv):
        try:
            obj.release()
        except Exception:
            pass
    vbo_pos = ctx.buffer(new_v.tobytes())
    vbo_nrm = ctx.buffer(new_n.tobytes())
    vbo_uv = ctx.buffer(new_uv.tobytes())
    vao = ctx.vertex_array(prog, [(vbo_pos, '3f', 'in_pos'),
                                  (vbo_nrm, '3f', 'in_normal'),
                                  (vbo_uv, '2f', 'in_uv')])

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
        self._loaded_model_path = model_path
        
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
                
            upload_mesh_buffers(verts, normals, tex_uv)
            
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
        should_reset = model_path != self._loaded_model_path
        if should_reset:
            reset_model_cache_dir()
            self._loaded_model_path = model_path
        try:
            verts, normals, tex_uv, Iz, tex_image = build_mesh_data(model_path, data.get("custom_texture", ""), cfg)
        except Exception as e:
            ToastWindow(f"模型加载失败: {e}", 3000).show()
            return
        
        upload_mesh_buffers(verts, normals, tex_uv)
        
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
