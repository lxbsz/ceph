#!/usr/bin/env bash

set -ex

git clone https://github.com/pantheon-systems/iozone.git iozone_src
cd iozone_src/src/current
make -j4
cd -
cp iozone_src/src/current/iozone .

./iozone -c -e -s 1024M -r 16K -t 1 -F f1 -i 0 -i 1
./iozone -c -e -s 1024M -r 1M -t 1 -F f2 -i 0 -i 1
./iozone -c -e -s 10240M -r 1M -t 1 -F f3 -i 0 -i 1
