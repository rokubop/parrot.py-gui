import sys
from gui.app import create_app

def main():
    app = create_app(sys.argv)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
