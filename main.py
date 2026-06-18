import sys
import threading
import os
import socket

# 🔧 ВОЗВРАЩАЕМ ТО, ЧТО РАБОТАЛО:
# Эти флаги ОБЯЗАТЕЛЬНО должны быть в самом верху файла до импорта PyQt6.
# Они снимают изоляцию Windows с браузера, разрешая ему открыть localhost.
sys.argv.append("--no-sandbox")
sys.argv.append("--test-type")
sys.argv.append("--ignore-certificate-errors")


def resource_path(relative_path):
    """ Получает абсолютный путь к ресурсу, работает для dev-режима и для PyInstaller """
    try:
        # PyInstaller создает временную папку и сохраняет путь в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest
from PyQt6.QtGui import QIcon

from app import app as flask_app


class FlaskThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True

    def run(self):
        # Запускаем Flask на имени localhost
        flask_app.run(host="localhost", port=5000, debug=False, use_reloader=False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ИИ Проверка работ")
        self.resize(900, 600)

        # 🎯 УСТАНОВКА ВШИТОЙ ИКОНКИ ДЛЯ ОКНА ПРИЛОЖЕНИЯ
        icon_embedded_path = resource_path("icon.png")
        self.setWindowIcon(QIcon(icon_embedded_path))

        self.browser = QWebEngineView()
        self.setCentralWidget(self.browser)

        # Перехват скачивания файлов Excel через проводник
        self.browser.page().profile().downloadRequested.connect(self.handle_download)

        # Рисуем красивый HTML-спиннер загрузки
        self.show_loading_spinner()

        # Каждую 1 секунду проверяем сокет Flask
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_flask_status)
        self.check_timer.start(1000)

    def check_flask_status(self):
        """Проверяет готовность сервера Flask"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("localhost", 5000))
            s.close()
            self.check_timer.stop()
            # Открываем интерфейс на localhost
            self.browser.setUrl(QUrl("http://localhost:5000/"))
            print(" Лог: Сервер Flask успешно обнаружен. Интерфейс прогружен!")
        except (socket.timeout, ConnectionRefusedError):
            pass

    def handle_download(self, download_item: QWebEngineDownloadRequest):
        """Открывает стандартное окно проводника Windows при скачивании результатов"""
        suggested_name = download_item.suggestedFileName()

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить результаты проверки",
            suggested_name,
            "Excel Files (*.xlsx)"
        )

        if file_path:
            download_item.setDownloadDirectory(os.path.dirname(file_path))
            download_item.setDownloadFileName(os.path.basename(file_path))
            download_item.accept()
            print(f" Лог: Итоговый Excel успешно сохранен по адресу: {file_path}")
        else:
            download_item.cancel()

    def show_loading_spinner(self):
        loading_html = """
        <html>
        <head>
        <style>
            body { display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #fafafa; font-family: sans-serif; color: #555; margin: 0; }
            .container { text-align: center; }
            .loader { border: 6px solid #e2e8f0; border-top: 6px solid #3498db; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite; margin: 0 auto 20px; }
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        </style>
        </head>
        <body>
            <div class="container">
                <div class="loader"></div>
                <h3>Запуск ИИ-агента...</h3>
                <p>Настройка локального окружения</p>
            </div>
        </body>
        </html>
        """
        self.browser.setHtml(loading_html)

    def closeEvent(self, event):
        print("Закрытие окна приложения. Сервер останавливается...")
        QApplication.quit()
        sys.exit(0)


if __name__ == "__main__":
    # 🔧 ФИКС ИКОНКИ ДЛЯ ПАНЕЛИ ЗАДАЧ WINDOWS:
    # Заставляем ОС определять приложение как уникальный процесс, а не как ID интерпретатора Python
    import ctypes

    myappid = 'Olympiad_Practices.AI_checker.1.0'  # Любая уникальная строка
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    # 1. Запуск сервера Flask в фоне
    server_thread = FlaskThread()
    server_thread.start()

    # 2. Запуск графического окна
    qt_app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(qt_app.exec())
