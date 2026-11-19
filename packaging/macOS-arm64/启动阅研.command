#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ "$(uname -m)" != arm64 ]]; then
  print "This package requires an Apple Silicon Mac (M series)."
  read "?Press Return to close."
  exit 1
fi
if [[ ! -x runtime/python/bin/python3 ]]; then
  print "Python runtime is missing. Extract the complete ZIP first."
  read "?Press Return to close."
  exit 1
fi
runtime/python/bin/python3 -E -s -B -X utf8 -u launch.py "$@"
task_result=$?
if (( task_result != 0 )); then
  print "Paper Desk could not start. Keep the error message above."
  read "?Press Return to close."
fi
exit $task_result
