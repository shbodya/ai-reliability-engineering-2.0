#!/usr/bin/env bash
# Record all stage demos as asciinema casts then upload.
# Prereqs:
#   brew install asciinema           # macOS
#   asciinema auth                   # link to asciinema.org account (optional, for upload)
# Output: lab-04/casts/stage{2,3,4,5}.cast + public URLs after upload.
set -e
cd "$(dirname "$0")/.."
mkdir -p casts

for s in 2 3 4 5; do
  echo
  echo "##### Recording stage $s #####"
  asciinema rec -c "./scripts/demo-stage${s}.sh" --overwrite "casts/stage${s}.cast"
done

echo
echo "##### Uploading #####"
for s in 2 3 4 5; do
  echo "stage$s:"
  asciinema upload "casts/stage${s}.cast" | tee -a casts/urls.txt
done

echo
echo "URLs saved to casts/urls.txt"
