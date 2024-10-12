import sys
import requests
from bs4 import BeautifulSoup
import re
import os
import shutil
import psutil
from urllib.parse import urljoin
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QProgressBar, QComboBox, QFileDialog, QTabWidget, QCheckBox, QDesktopWidget
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QThread, pyqtSignal, QProcess
from datetime import datetime

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

ffmpeg_path = resource_path("ffmpeg/ffmpeg")
ffprobe_path = resource_path("ffmpeg/ffprobe")
logo_path = resource_path("assets/logo.png")
intro_path = resource_path("assets/intro.mp4")
outro_path = resource_path("assets/outro.mp4")
seal_path = resource_path("zgyz_seal.ico")

class DownloadThread(QThread):
    progress_update = pyqtSignal(int, int, int, int)
    download_complete = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, urls, cdnurl):
        super().__init__()
        self.urls = urls
        self.cdnurl = cdnurl

    def run(self):
        for i, url in enumerate(self.urls):
            guid, m3u8_url = self.get_webpage_extract_guid_and_generate_m3u8_url(url)
            if guid and m3u8_url:
                self.download_and_process_m3u8(guid, m3u8_url, i+1, len(self.urls))
            else:
                self.error_occurred.emit(f"无法获取 GUID 或生成 m3u8 URL: {url}")

    def get_webpage_extract_guid_and_generate_m3u8_url(self, url):
        try:
            response = requests.get(url, proxies={'http': None, 'https': None})
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                guid_pattern = r'var\s+guid(?:_0)?\s*=\s*"([^"]+)"'
                video_center_id_pattern = r'videoCenterId:\s*"([^"]+)"'
                script_tags = soup.find_all('script')
                for script in script_tags:
                    if script.string:
                        guid_match = re.search(guid_pattern, script.string)
                        if guid_match:
                            guid = guid_match.group(1)
                            m3u8_url = f"https://{self.cdnurl}/asp/hls/2000/0303000a/3/default/{guid}/2000.m3u8"
                            return guid, m3u8_url

                video_center_id_match = re.search(video_center_id_pattern, response.text)
                if video_center_id_match:
                    video_center_id = video_center_id_match.group(1)
                    m3u8_url = f"https://{self.cdnurl}/asp/hls/2000/0303000a/3/default/{video_center_id}/2000.m3u8"
                    return video_center_id, m3u8_url

            return None, None
        except Exception as e:
            print(f"Error: {e}")
            return None, None

    def download_and_process_m3u8(self, guid, m3u8_url, current_video, total_videos):
        base_dir = os.path.join(os.getcwd(), datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(base_dir, exist_ok=True)
        temp_dir = os.path.join(base_dir, 'cctv_temp')
        os.makedirs(temp_dir, exist_ok=True)

        try:
            m3u8_response = requests.get(m3u8_url)
            m3u8_content = m3u8_response.text

            ts_urls = [line.strip() for line in m3u8_content.split('\n') if line.strip().endswith('.ts')]

            for i, ts_url in enumerate(ts_urls):
                full_url = urljoin(m3u8_url, ts_url)
                ts_response = requests.get(full_url)
                ts_file_path = os.path.join(temp_dir, f"{i}.ts")
                with open(ts_file_path, 'wb') as f:
                    f.write(ts_response.content)
                self.progress_update.emit(current_video, total_videos, i + 1, len(ts_urls))

            output_file = os.path.join(base_dir, f"{guid}.mp4")
            with open(os.path.join(temp_dir, 'file_list.txt'), 'w') as f:
                for i in range(len(ts_urls)):
                    f.write(f"file '{i}.ts'\n")

            ffmpeg_command = [ffmpeg_path, '-y', '-f', 'concat', '-safe', '0', '-i', os.path.join(temp_dir, 'file_list.txt'), '-c', 'copy', output_file]
            subprocess.run(ffmpeg_command, check=True, creationflags=subprocess.CREATE_NO_WINDOW)

            self.download_complete.emit(output_file)

        except subprocess.CalledProcessError as e:
            self.error_occurred.emit(f"FFmpeg 执行错误: {e}")
        except Exception as e:
            self.error_occurred.emit(f"发生错误: {e}")
        finally:
            shutil.rmtree(temp_dir)

class MergeThread(QThread):
    progress_update = pyqtSignal(int, int, str)
    merge_complete = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, folder, watermark_image, add_intro, add_ending, acceleration):
        super().__init__()
        self.folder = folder
        self.watermark_image = watermark_image
        self.add_intro = add_intro
        self.add_ending = add_ending
        self.acceleration = acceleration

    def run(self):
        video_files = [f for f in os.listdir(self.folder) if f.endswith('.mp4')]
        total_videos = len(video_files)
        if not video_files:
            self.error_occurred.emit("所选文件夹中没有找到 MP4 文件")
            return

        output_file = os.path.join(self.folder, "merged_output.mp4")
        temp_dir = os.path.join(self.folder, 'temp_processed')
        os.makedirs(temp_dir, exist_ok=True)

        try:
            processed_files = []
            
            if self.add_intro:
                processed_files.append(intro_path)

            for i, video in enumerate(video_files):
                input_video = os.path.join(self.folder, video)
                output_video = os.path.join(temp_dir, f"processed_{i}.mp4")

                ffmpeg_args = [
                    '-y',
                    '-i', input_video,
                ]

                if self.acceleration == "英伟达（Nvidia）":
                    ffmpeg_args.extend(['-hwaccel', 'cuda'])
                elif self.acceleration == "AMD":
                    ffmpeg_args.extend(['-hwaccel', 'amf'])

                filter_complex = []

                filter_complex.append('[0:v]scale=1280:720,fps=25[scaled]')

                if self.watermark_image:
                    ffmpeg_args.extend(['-i', self.watermark_image])
                    watermark_height = int(720 * 0.10)
                    margin = int(watermark_height * 0.5)
                    filter_complex.extend([
                        f'[1:v]scale=-1:{watermark_height}[watermark]',
                        f'[scaled][watermark]overlay=W-w-{margin}:{margin}[out]'
                    ])
                else:
                    filter_complex.append('[scaled]copy[out]')

                filter_complex =';'.join(filter_complex)
                ffmpeg_args.extend([
                    '-filter_complex', filter_complex,
                    '-map', '[out]',
                    '-map', '0:a',
                    '-c:v', 'h264_nvenc' if self.acceleration == "英伟达（Nvidia）" else ('h264_amf' if self.acceleration == "AMD" else 'libx264'),
                    '-crf', '23',
                    '-preset', 'medium',
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    output_video
                ])

                ffmpeg_process = QProcess()
                ffmpeg_process.setProcessChannelMode(QProcess.MergedChannels)
                ffmpeg_process.start(ffmpeg_path, ffmpeg_args)

                probe = subprocess.run([ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_video], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                duration = float(probe.stdout)

                while ffmpeg_process.state() != QProcess.NotRunning:
                    ffmpeg_process.waitForReadyRead(100)
                    output = ffmpeg_process.readAllStandardOutput().data().decode()
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})', output)
                    if time_match:
                        hours, minutes, seconds = map(float, time_match.groups())
                        current_time = hours * 3600 + minutes * 60 + seconds
                        progress = int((current_time / duration) * 100)
                        overall_progress = int(((i + progress /100) / total_videos) * 100)
                        self.progress_update.emit(overall_progress,100, f"处理视频 {i+1}/{total_videos}，当前进度: {progress}%")

                if ffmpeg_process.exitCode() != 0:
                    raise subprocess.CalledProcessError(ffmpeg_process.exitCode(),'ffmpeg')

                processed_files.append(output_video)

            if self.add_ending:
                processed_files.append(outro_path)

            with open(os.path.join(temp_dir, 'processed_list.txt'), 'w') as f:
                for file in processed_files:
                    f.write(f"file '{file}'\n")

            merge_process = QProcess()
            merge_process.setProcessChannelMode(QProcess.MergedChannels)
            merge_args = [
                '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', os.path.join(temp_dir, 'processed_list.txt'),
                '-c', 'copy',
                output_file
            ]
            if self.acceleration == "英伟达（Nvidia）":
                merge_args.extend(['-hwaccel', 'cuda'])
            elif self.acceleration == "AMD":
                merge_args.extend(['-hwaccel', 'amf'])
            merge_process.start(ffmpeg_path, merge_args)
            merge_process.waitForFinished(-1)

            if merge_process.exitCode() != 0:
                raise subprocess.CalledProcessError(merge_process.exitCode(), 'ffmpeg')

            self.merge_complete.emit(output_file)

        except subprocess.CalledProcessError as e:
            self.error_occurred.emit(f"处理视频时出错: {e}")
        except Exception as e:
            self.error_occurred.emit(f"发生错误: {e}")
        finally:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] == 'ffmpeg':
                    proc.kill()
            
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                self.error_occurred.emit(f"删除临时目录时出错: {e}")

class ConversionThread(QThread):
    progress_update = pyqtSignal(int, int, str)
    conversion_complete = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, input_file, output_file, resolution, format, acceleration):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.resolution = resolution
        self.format = format
        self.acceleration = acceleration

    def run(self):
        try:
            probe = subprocess.run([ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', self.input_file], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            duration = float(probe.stdout)

            if self.resolution == '720p':
                resolution = '1280:720'
            elif self.resolution == '480p':
                resolution = '854:480'
            else:# 320p
                resolution = '480:320'

            command = [
                ffmpeg_path,
                '-i', self.input_file,
                '-vf', f'scale={resolution}',
                '-c:v', 'mpeg2video' if self.format == 'mpg' else 'mpeg4',
                '-c:a', 'mp2' if self.format == 'mpg' else 'mp3',
                '-b:v', '4M',
                '-b:a', '192k',
                '-y',
                self.output_file
            ]

            if self.acceleration == "英伟达（Nvidia）":
                command.extend(['-hwaccel', 'cuda'])
                if self.format != 'mpg':
                    command[command.index('-c:v') + 1] = 'h264_nvenc'
            elif self.acceleration == "AMD":
                command.extend(['-hwaccel', 'amf'])
                if self.format != 'mpg':
                    command[command.index('-c:v') + 1] = 'h264_amf'

            process = subprocess.Popen(command, stderr=subprocess.PIPE, universal_newlines=True, creationflags=subprocess.CREATE_NO_WINDOW)

            for line in process.stderr:
                if 'time=' in line:
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}.\d{2})', line)
                    if time_match:
                        hours, minutes, seconds = map(float, time_match.groups())
                        current_time = hours * 3600 + minutes * 60 + seconds
                        progress = int((current_time / duration) * 100)
                        self.progress_update.emit(progress, 100, f"转换进度: {progress}%")

            process.wait()

            if process.returncode == 0:
                self.conversion_complete.emit(self.output_file)
            else:
                self.error_occurred.emit("转换过程中出错")

        except Exception as e:
            self.error_occurred.emit(f"发生错误: {str(e)}")

class DownloaderGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.cdn_urls = {
            "3rd华为": "hls.cntv.myhwcdn.cn",
            "3rd网宿": "vod.cntv.lxdns.com",
            "3rd网宿海外（超清，需代理hls.cntv.cdn20.com）": "hls.cntv.cdn20.com"
        }
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        # Add FFmpeg acceleration dropdown
        acceleration_layout = QHBoxLayout()
        acceleration_layout.addWidget(QLabel('FFmpeg加速:'))
        self.acceleration_combo = QComboBox()
        self.acceleration_combo.addItems(['不加速（CPU）', '英伟达（Nvidia）', 'AMD'])
        acceleration_layout.addWidget(self.acceleration_combo)
        layout.addLayout(acceleration_layout)

        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self.create_download_tab(), "下载视频")
        self.tab_widget.addTab(self.create_merge_tab(), "合并视频")
        self.tab_widget.addTab(self.create_conversion_tab(), "格式转换")

        layout.addWidget(self.tab_widget)

        self.setLayout(layout)
        self.setWindowTitle('自贡一中放送系统')
        self.setWindowIcon(QIcon(seal_path))
        
        screen = QDesktopWidget().screenNumber(self)
        screen_size = QDesktopWidget().screenGeometry(screen)
        
        width = int(screen_size.width() * 0.35)
        height = int(screen_size.height() * 0.45)
        x = (screen_size.width() - width) // 2
        y = (screen_size.height() - height) // 2
        
        self.setGeometry(x, y, width, height)

    def create_download_tab(self):
        download_widget = QWidget()
        layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel('URLs:'))
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("每行输入一个URL")
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)

        cdn_layout = QHBoxLayout()
        cdn_layout.addWidget(QLabel('CDN:'))
        self.cdn_combo = QComboBox()
        self.cdn_combo.addItems(list(self.cdn_urls.keys()))
        cdn_layout.addWidget(self.cdn_combo)
        layout.addLayout(cdn_layout)

        self.download_btn = QPushButton('开始下载')
        self.download_btn.clicked.connect(self.start_download)
        layout.addWidget(self.download_btn)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        layout.addWidget(self.status_text)

        download_widget.setLayout(layout)
        return download_widget

    def create_merge_tab(self):
        merge_widget = QWidget()
        layout = QVBoxLayout()

        folder_layout = QHBoxLayout()
        self.folder_input = QTextEdit()
        self.folder_input.setPlaceholderText("选择包含视频文件的文件夹")
        folder_layout.addWidget(self.folder_input)
        self.folder_btn = QPushButton('选择文件夹')
        self.folder_btn.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_btn)
        layout.addLayout(folder_layout)

        self.add_intro_checkbox = QCheckBox('添加片头')
        self.add_intro_checkbox.setChecked(True)
        layout.addWidget(self.add_intro_checkbox)

        self.add_watermark_checkbox = QCheckBox('添加水印')
        self.add_watermark_checkbox.setChecked(True)
        layout.addWidget(self.add_watermark_checkbox)

        self.add_ending_checkbox = QCheckBox('添加片尾')
        self.add_ending_checkbox.setChecked(True)
        layout.addWidget(self.add_ending_checkbox)

        self.merge_btn = QPushButton('合并视频')
        self.merge_btn.clicked.connect(self.merge_videos)
        layout.addWidget(self.merge_btn)

        self.merge_progress_bar = QProgressBar()
        layout.addWidget(self.merge_progress_bar)

        self.merge_status_text = QTextEdit()
        self.merge_status_text.setReadOnly(True)
        layout.addWidget(self.merge_status_text)

        merge_widget.setLayout(layout)
        return merge_widget

    def create_conversion_tab(self):
        conversion_widget = QWidget()
        layout = QVBoxLayout()

        file_layout = QHBoxLayout()
        self.file_input = QTextEdit()
        self.file_input.setPlaceholderText("选择要转换的视频文件")
        file_layout.addWidget(self.file_input)
        self.file_btn = QPushButton('选择文件')
        self.file_btn.clicked.connect(self.select_file)
        file_layout.addWidget(self.file_btn)
        layout.addLayout(file_layout)

        resolution_layout = QHBoxLayout()
        resolution_layout.addWidget(QLabel('分辨率:'))
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(['720p (汇北校区)', '480p (新街校区)', '320p'])
        resolution_layout.addWidget(self.resolution_combo)
        layout.addLayout(resolution_layout)

        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel('目标格式:'))
        self.format_combo = QComboBox()
        self.format_combo.addItems(['mpg', 'avi'])
        format_layout.addWidget(self.format_combo)
        layout.addLayout(format_layout)

        self.convert_btn = QPushButton('开始转换')
        self.convert_btn.clicked.connect(self.start_conversion)
        layout.addWidget(self.convert_btn)

        self.conversion_progress_bar = QProgressBar()
        layout.addWidget(self.conversion_progress_bar)

        self.conversion_status_text = QTextEdit()
        self.conversion_status_text.setReadOnly(True)
        layout.addWidget(self.conversion_status_text)

        conversion_widget.setLayout(layout)
        return conversion_widget

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self.folder_input.setText(folder)

    def select_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.avi *.mov*.mkv)")
        if file:
            self.file_input.setText(file)

    def merge_videos(self):
        folder = self.folder_input.toPlainText()
        if not folder or not os.path.isdir(folder):
            self.merge_status_text.setText("请选择有效的文件夹")
            return

        add_intro = self.add_intro_checkbox.isChecked()
        add_watermark = self.add_watermark_checkbox.isChecked()
        add_ending = self.add_ending_checkbox.isChecked()

        watermark_image = logo_path if add_watermark else None
        if add_watermark and not os.path.exists(watermark_image):
            self.merge_status_text.setText("找不到水印图片(logo.png)")
            return

        if add_intro and not os.path.exists(intro_path):
            self.merge_status_text.setText("找不到片头视频 (intro.mp4)")
            return

        if add_ending and not os.path.exists(outro_path):
            self.merge_status_text.setText("找不到片尾视频 (outro.mp4)")
            return

        acceleration = self.acceleration_combo.currentText()

        self.merge_thread = MergeThread(folder, watermark_image, add_intro, add_ending, acceleration)
        self.merge_thread.progress_update.connect(self.update_merge_progress)
        self.merge_thread.merge_complete.connect(self.merge_finished)
        self.merge_thread.error_occurred.connect(self.show_merge_error)
        self.merge_thread.start()

        self.merge_btn.setEnabled(False)
        self.merge_status_text.setText("开始处理视频...")

    def update_merge_progress(self, current, total, message):
        self.merge_progress_bar.setValue(current)
        self.merge_status_text.setText(message)

    def merge_finished(self, output_file):
        self.merge_progress_bar.setValue(100)
        self.merge_status_text.append(f"视频合并完成: {output_file}")
        self.merge_btn.setEnabled(True)

    def show_merge_error(self, error_message):
        self.merge_status_text.append(error_message)
        self.merge_btn.setEnabled(True)

    def start_download(self):
        urls = self.url_input.toPlainText().split('\n')
        urls = [url.strip() for url in urls if url.strip()]
        cdn_name = self.cdn_combo.currentText()
        cdnurl = self.cdn_urls[cdn_name]
        if not urls:
            self.status_text.setText("请输入至少一个 URL")
            return

        self.download_thread = DownloadThread(urls, cdnurl)
        self.download_thread.progress_update.connect(self.update_progress)
        self.download_thread.download_complete.connect(self.download_finished)
        self.download_thread.error_occurred.connect(self.show_error)
        self.download_thread.start()

        self.download_btn.setEnabled(False)
        self.status_text.setText("下载中...")

    def update_progress(self, current_video, total_videos, current_segment, total_segments):
        progress = int((current_video - 1) / total_videos * 100+ (current_segment / total_segments) * (100 /total_videos))
        self.progress_bar.setValue(progress)
        self.status_text.setText(f"下载视频 {current_video}/{total_videos}，当前视频进度 {current_segment}/{total_segments}")

    def download_finished(self, output_file):
        self.status_text.append(f"下载完成: {output_file}")
        self.download_btn.setEnabled(True)

    def show_error(self, error_message):
        self.status_text.append(error_message)
        self.download_btn.setEnabled(True)

    def start_conversion(self):
        input_file = self.file_input.toPlainText()
        if not input_file or not os.path.isfile(input_file):
            self.conversion_status_text.setText("请选择有效的视频文件")
            return

        resolution = self.resolution_combo.currentText().split()[0]
        format = self.format_combo.currentText()
        acceleration = self.acceleration_combo.currentText()

        output_file = os.path.splitext(input_file)[0] + f"_{resolution}.{format}"

        self.conversion_thread = ConversionThread(input_file, output_file, resolution, format, acceleration)
        self.conversion_thread.progress_update.connect(self.update_conversion_progress)
        self.conversion_thread.conversion_complete.connect(self.conversion_finished)
        self.conversion_thread.error_occurred.connect(self.show_conversion_error)
        self.conversion_thread.start()

        self.convert_btn.setEnabled(False)
        self.conversion_status_text.setText("开始转换...")

    def update_conversion_progress(self, current, total, message):
        self.conversion_progress_bar.setValue(current)
        self.conversion_status_text.setText(message)

    def conversion_finished(self, output_file):
        self.conversion_progress_bar.setValue(100)
        self.conversion_status_text.setText(f"转换完成: {output_file}")
        self.convert_btn.setEnabled(True)

    def show_conversion_error(self, error_message):
        self.conversion_status_text.setText(error_message)
        self.convert_btn.setEnabled(True)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = DownloaderGUI()
    ex.show()
    sys.exit(app.exec_())