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
    SLOW_SPEED = 10
    CHECK_INTERVAL_MINUTES = 1
    QUIET_HOURS_RANGE = [22, 8]
    ROUTER_PIN = 10
    MODEM_PIN = 11
    BUTTON_PIN = 23
    NORMAL_LED_PIN = 25
    SLOW_LED_PIN = 18
    REBOOTING_LED_PIN = 15
    BUZZER_PIN = 21
    REBOOT_DELAY_SECONDS = 10
    ROUTER_DELAY_SECONDS = 10
    MANUAL_REBOOT_SECONDS = 5

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
        self.router = DigitalOutputDevice(self.ROUTER_PIN, initial=GPIO.HIGH)
        self.modem = DigitalOutputDevice(self.MODEM_PIN, initial=GPIO.HIGH)
        self.normal_led = LED(self.NORMAL_LED_PIN)
        self.slow_led = LED(self.SLOW_LED_PIN)
        self.rebooting_led = LED(self.REBOOTING_LED_PIN)
        self.button = Button(self.BUTTON_PIN, self.button_pressed, self.MANUAL_REBOOT_SECONDS, self.button_held)
        self.buzzer = Buzzer(self.BUZZER_PIN, 10000, self.QUIET_HOURS_RANGE)
        self.download_speed = self.SLOW_SPEED
        self.to_normal()

    def check_speed(self):
        self.slow_led.off()
        self.normal_led.off()
        self.rebooting_led.on()
        s = speedtest.Speedtest()
        s.get_best_server()
        s.download()
        self.download_speed = s.results.download / 10**6
        log.debug('Download speed = {} MBps'.format(self.download_speed))
        self.update()

    def sleep(self):
        sleep(self.CHECK_INTERVAL_MINUTES * 60.0)

    def can_go_normal(self):
        return self.download_speed >= self.SLOW_SPEED

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
        self.modem.off()
        self.router.off()
        sleep(self.REBOOT_DELAY_SECONDS)
        self.modem.on()
        sleep(self.ROUTER_DELAY_SECONDS)
        self.router.on()
        self.to_normal()

    def cleanup(self):
        self.buzzer.stop()
        self.normal_led.off()
        self.slow_led.off()
        GPIO.cleanup()
