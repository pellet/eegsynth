#!/usr/bin/env python

# This module shows images on screen and can be used for stimulus presentation.
#
# This software is part of the EEGsynth project, see <https://github.com/eegsynth/eegsynth>.
#
# Copyright (C) 2022 EEGsynth project
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

from PyQt5 import QtGui, QtCore, QtWidgets
from PyQt5.QtWidgets import QApplication, QWidget
import configparser
import redis
import argparse
import os
import sys
import time
import threading
import signal

if hasattr(sys, 'frozen'):
    path = os.path.split(sys.executable)[0]
    file = os.path.split(sys.executable)[-1]
    name = os.path.splitext(file)[0]
elif __name__=='__main__' and sys.argv[0] != '':
    path = os.path.split(sys.argv[0])[0]
    file = os.path.split(sys.argv[0])[-1]
    name = os.path.splitext(file)[0]
elif __name__=='__main__':
    path = os.path.abspath('')
    file = os.path.split(path)[-1] + '.py'
    name = os.path.splitext(file)[0]
else:
    path = os.path.split(__file__)[0]
    file = os.path.split(__file__)[-1]
    name = os.path.splitext(file)[0]

# eegsynth/lib contains shared modules
sys.path.insert(0, os.path.join(path, '../../lib'))
import EEGsynth


class TriggerThread(threading.Thread):
    def __init__(self, redischannel, image):
        threading.Thread.__init__(self)
        monitor.info("%s = %s" % (redischannel, image))
        self.redischannel = redischannel
        self.image = QtGui.QPixmap(image)                   # load the image from file
        self.image = self.image.scaled(winwidth, winheight) # scale the image to the window
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        global r, patch, lock, monitor
        pubsub = r.pubsub()
        pubsub.subscribe('PLOTIMAGE_UNBLOCK')  # this message unblocks the redis listen command
        pubsub.subscribe(self.redischannel)  # this message contains the trigger
        while self.running:
            for item in pubsub.listen():
                if not self.running or not item['type'] == 'message':
                    break
                if item['channel'] == self.redischannel:
                    window.setImage(self.image)
                    window.paintEvent(None)
                        

class Window(QWidget):
    def __init__(self):
        super(Window, self).__init__()
        self.setGeometry(winx, winy, winwidth, winheight)
        # self.setFixedSize(winwidth, winheight)
        self.setStyleSheet('background-color:black;');
        self.setWindowTitle(patch.getstring('display', 'title', default='EEGsynth plotimage'))
        self.image = None

        self.label = QtWidgets.QLabel() # this will contain the pixmap
        self.label.setAlignment(QtCore.Qt.AlignCenter)

        g = QtWidgets.QGridLayout()
        g.setContentsMargins(0,0,0,0)
        g.addWidget(self.label,0,1)
        self.setLayout(g)

    def setImage(self, image):
        self.image = image
        
    def paintEvent(self, e):
        if not self.image == None:
            self.label.setPixmap(self.image)
        self.show()


def _setup():
    '''Initialize the module
    This adds a set of global variables
    '''
    global parser, args, config, r, response, patch

    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--inifile", default=os.path.join(path, name + '.ini'), help="name of the configuration file")
    args = parser.parse_args()

    config = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
    config.read(args.inifile)

    try:
        r = redis.StrictRedis(host=config.get('redis', 'hostname'), port=config.getint('redis', 'port'), db=0, charset='utf-8', decode_responses=True)
        response = r.client_list()
    except redis.ConnectionError:
        raise RuntimeError("cannot connect to Redis server")

    # combine the patching from the configuration file and Redis
    patch = EEGsynth.patch(config, r)

    # there should not be any local variables in this function, they should all be global
    if len(locals()):
        print('LOCALS: ' + ', '.join(locals().keys()))


def _start():
    '''Start the module
    This uses the global variables from setup and adds a set of global variables
    '''
    global parser, args, config, r, response, patch, name
    global monitor, delay, winx, winy, winwidth, winheight, input_channel, input_image, app, window, triggers, timer

    # this can be used to show parameters that have changed
    monitor = EEGsynth.monitor(name=name, debug=patch.getint('general', 'debug'))

    # get the options from the configuration file
    delay           = patch.getfloat('general', 'delay')
    winx            = patch.getfloat('display', 'xpos')
    winy            = patch.getfloat('display', 'ypos')
    winwidth        = patch.getfloat('display', 'width')
    winheight       = patch.getfloat('display', 'height')

    # get the input options
    input_channel, input_image = list(zip(*config.items('input')))

    # start the graphical user interface
    app = QApplication(sys.argv)
    app.aboutToQuit.connect(_stop)
    signal.signal(signal.SIGINT, _stop)

    # Let the interpreter run every 400 ms
    # see https://stackoverflow.com/questions/4938723/what-is-the-correct-way-to-make-my-pyqt-application-quit-when-killed-from-the-co/6072360#6072360
    timer = QtCore.QTimer()
    timer.start(400)
    timer.timeout.connect(lambda: None)

    window = Window()
    window.show()

    triggers = []
    # make a trigger thread for each image
    for channel, image in zip(input_channel, input_image):
        triggers.append(TriggerThread(channel, image))
        
    # start the thread for each of the triggers
    for thread in triggers:
        thread.start()

    # there should not be any local variables in this function, they should all be global
    if len(locals()):
        print('LOCALS: ' + ', '.join(locals().keys()))


def _loop_once():
    '''Run the main loop once
    '''
    pass


def _loop_forever():
    '''Run the main loop forever
    '''
    QApplication.instance().exec_()


def _stop(*args):
    '''Stop and clean up on SystemExit, KeyboardInterrupt
    '''
    global monitor, r, triggers
    monitor.success('Closing threads')
    for thread in triggers:
        thread.stop()
    r.publish('PLOTIMAGE_UNBLOCK', 1)
    for thread in triggers:
        thread.join()
    QApplication.quit()


if __name__ == '__main__':
    _setup()
    _start()
    try:
        _loop_forever()
    except (SystemExit, KeyboardInterrupt, RuntimeError):
        _stop()
