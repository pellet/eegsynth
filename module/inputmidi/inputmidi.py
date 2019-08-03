#!/usr/bin/env python

# Inputmidi records MIDI data to Redis
#
# This software is part of the EEGsynth project, see <https://github.com/eegsynth/eegsynth>.
#
# Copyright (C) 2017-2019 EEGsynth project
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import configparser
import argparse
import mido
import os
import redis
import sys
import time

if hasattr(sys, 'frozen'):
    path = os.path.split(sys.executable)[0]
    file = os.path.split(sys.executable)[-1]
elif sys.argv[0] != '':
    path = os.path.split(sys.argv[0])[0]
    file = os.path.split(sys.argv[0])[-1]
else:
    path = os.path.abspath('')
    file = os.path.split(path)[-1] + '.py'

# eegsynth/lib contains shared modules
sys.path.insert(0, os.path.join(path,'../../lib'))
import EEGsynth

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--inifile", default=os.path.join(path, os.path.splitext(file)[0] + '.ini'), help="optional name of the configuration file")
args = parser.parse_args()

config = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
config.read(args.inifile)

try:
    r = redis.StrictRedis(host=config.get('redis','hostname'), port=config.getint('redis','port'), db=0)
    response = r.client_list()
except redis.ConnectionError:
    print("Error: cannot connect to redis server")
    exit()

# combine the patching from the configuration file and Redis
patch = EEGsynth.patch(config, r)

# this can be used to show parameters that have changed
monitor = EEGsynth.monitor()

# get the options from the configuration file
debug      = patch.getint('general','debug')
mididevice = patch.getstring('midi', 'device')
mididevice = EEGsynth.trimquotes(mididevice)

# the scale and offset are used to map MIDI values to Redis values
output_scale    = patch.getfloat('output', 'scale', default=1./127) # MIDI values are from 0 to 127
output_offset   = patch.getfloat('output', 'offset', default=0.)    # MIDI values are from 0 to 127

# this is only for debugging, check which MIDI devices are accessible
print('------ INPUT ------')
for port in mido.get_input_names():
  print(port)
print('-------------------------')

try:
    inputport  = mido.open_input(mididevice)
    if debug>0:
        print("Connected to MIDI input")
except:
    print("Error: cannot connect to MIDI input")
    exit()

while True:
    monitor.loop()
    time.sleep(patch.getfloat('general','delay'))

    for msg in inputport.iter_pending():

        if debug>1:
            print(msg)

        if hasattr(msg, "control"):
            # prefix.control000=value
            key = "{}.control{:0>3d}".format(patch.getstring('output', 'prefix'), msg.control)
            val = msg.value
            # map the MIDI values to Redis values between 0 and 1
            val = EEGsynth.rescale(val, slope=output_scale, offset=output_offset)
            patch.setvalue(key, val, debug=debug)

        elif hasattr(msg, "note"):
            # prefix.noteXXX=value
            key = "{}.note{:0>3d}".format(patch.getstring('output','prefix'), msg.note)
            val = msg.velocity
            patch.setvalue(key, val, debug=debug)
            key = "{}.note".format(patch.getstring('output','prefix'))
            val = msg.note
            patch.setvalue(key, val, debug=debug)
