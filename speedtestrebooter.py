from ast import literal_eval
from ConfigParser import ConfigParser
import logging
from time import sleep

import RPi.GPIO as GPIO
import speedtest
from transitions import Machine
from transitions.extensions.states import add_state_features, Timeout

from raspberrypi_utils.input_devices import Button
from raspberrypi_utils.output_devices import Buzzer, DigitalOutputDevice, LED

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.WARNING)
log = logging.getLogger()


@add_state_features(Timeout)
class TimeoutMachine(Machine):
    pass


class SpeedTestRebooter(TimeoutMachine):
    def __init__(self):
        states = [
            'normal',
            'low',
            {'name': 'warn_reboot', 'timeout': 30, 'on_timeout': 'warn_expired'},
            'rebooting',
        ]
        transitions = [
            {
                'trigger': 'update',
                'source': 'normal',
                'dest': 'low',
                'conditions': 'can_go_low',
            },
            {
                'trigger': 'update',
                'source': 'low',
                'dest': 'warn_reboot',
                'conditions': 'can_go_low',
            },
            {
                'trigger': 'warn_expired',
                'source': 'warn_reboot',
                'dest': 'rebooting',
                'after': 'reboot'
            },
            {
                'trigger': 'update',
                'source': ['low', 'normal', 'warn_reboot'],
                'dest': 'normal',
                'conditions': 'can_go_normal',
            },
            {
                'trigger': 'button_pressed',
                'source': ['low', 'warn_reboot'],
                'dest': 'normal',
            },
            {
                'trigger': 'button_held',
                'source': ['low', 'normal'],
                'dest': 'rebooting',
                'after': 'reboot'
            },
        ]
        super(SpeedTestRebooter, self).__init__(
            states=states,
            transitions=transitions,
            initial='normal',
            ignore_invalid_triggers=True
        )

        GPIO.setmode(GPIO.BCM)
        self.config = self.read_config()
        self.router = DigitalOutputDevice(self.config['ROUTER_PIN'], initial=GPIO.HIGH)
        self.modem = DigitalOutputDevice(self.config['MODEM_PIN'], initial=GPIO.HIGH)
        self.normal_led = LED(self.config['NORMAL_LED_PIN'])
        self.slow_led = LED(self.config['SLOW_LED_PIN'])
        self.rebooting_led = LED(self.config['REBOOTING_LED_PIN'])
        self.button = Button(self.config['BUTTON_PIN'], self.button_pressed,
                             self.config['MANUAL_REBOOT_SECONDS'], self.button_held)
        self.buzzer = Buzzer(self.config['BUZZER_PIN'], 10000, self.config['QUIET_HOURS_RANGE'])
        self.download_speed = self.config['SLOW_SPEED']
        self.to_normal()

    @staticmethod
    def read_config():
        parser = ConfigParser()
        parser.read('config.ini')
        return {
            'BUTTON_PIN': parser.getint('Config', 'BUTTON_PIN'),
            'BUZZER_PIN': parser.getint('Config', 'BUZZER_PIN'),
            'CHECK_INTERVAL_MINUTES': parser.getfloat('Config', 'CHECK_INTERVAL_MINUTES'),
            'MANUAL_REBOOT_SECONDS': parser.getint('Config', 'MANUAL_REBOOT_SECONDS'),
            'MODEM_PIN': parser.getint('Config', 'MODEM_PIN'),
            'NORMAL_LED_PIN': parser.getint('Config', 'NORMAL_LED_PIN'),
            'QUIET_HOURS_RANGE': literal_eval(parser.get('Config', 'QUIET_HOURS_RANGE')),
            'REBOOT_DELAY_SECONDS': parser.getint('Config', 'REBOOT_DELAY_SECONDS'),
            'REBOOTING_LED_PIN': parser.getint('Config', 'REBOOTING_LED_PIN'),
            'ROUTER_DELAY_SECONDS': parser.getint('Config', 'ROUTER_DELAY_SECONDS'),
            'ROUTER_PIN': parser.getint('Config', 'ROUTER_PIN'),
            'SLOW_LED_PIN': parser.getint('Config', 'SLOW_LED_PIN'),
            'SLOW_SPEED': parser.getfloat('Config', 'SLOW_SPEED'),
        }

    def check_speed(self):
        self.slow_led.off()
        self.normal_led.off()
        self.rebooting_led.on()
        s = speedtest.Speedtest()
        s.get_best_server()
        s.download()
        self.download_speed = s.results.download / 10**6
        log.debug('Download speed = {:.2f} MBps'.format(self.download_speed))
        self.update()

    def sleep(self):
        sleep(self.config['CHECK_INTERVAL_MINUTES'] * 60.0)

    def can_go_normal(self):
        return self.download_speed >= self.config['SLOW_SPEED']

    def can_go_low(self):
        return not self.can_go_normal()

    def on_enter_low(self):
        self.buzzer.stop()
        self.normal_led.off()
        self.rebooting_led.off()
        self.slow_led.on()

    def on_enter_normal(self):
        self.buzzer.stop()
        self.slow_led.off()
        self.rebooting_led.off()
        self.normal_led.on()

    def on_enter_warn_reboot(self):
        self.normal_led.off()
        self.rebooting_led.off()
        self.slow_led.flash()
        self.buzzer.start()

    def on_exit_warn_reboot(self):
        self.slow_led.off()
        self.buzzer.stop()

    def on_enter_rebooting(self):
        self.normal_led.off()
        self.slow_led.off()
        self.rebooting_led.flash(on_seconds=1, off_seconds=0.5)

    def on_exit_rebooting(self):
        self.rebooting_led.off()

    def reboot(self):
        log.warning('Rebooting')
        self.modem.off()
        self.router.off()
        sleep(self.config['REBOOT_DELAY_SECONDS'])
        self.modem.on()
        sleep(self.config['ROUTER_DELAY_SECONDS'])
        self.router.on()
        self.to_normal()

    def cleanup(self):
        self.buzzer.stop()
        self.normal_led.off()
        self.slow_led.off()
        GPIO.cleanup()
