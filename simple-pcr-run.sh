#!/bin/bash

cd /root/OpenPyCR

python3 openpycr.py send -p Programs/ArcFreezer.pcr
PCR_STATUS=""
while [ "$PCR_STATUS" != "Program complete." ]; do
  PCR_STATUS="$(python3 openpycr.py status)"
  echo $PCR_STATUS
  sleep 1
done
