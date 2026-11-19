#!/bin/zsh
cd "${0:A:h}" || exit 1
runtime/python/bin/python3 -E -s -B -X utf8 diagnose.py
task_result=$?
read "?Press Return to close."
exit $task_result
