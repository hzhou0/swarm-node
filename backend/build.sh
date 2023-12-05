cd "$(dirname "$0")" || return
python -m nuitka --standalone ./main.py --output-dir=./dist