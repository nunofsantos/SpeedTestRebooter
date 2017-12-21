import logging
from logging.handlers import RotatingFileHandler
from time import sleep

from Adafruit_LED_Backpack import HT16K33, SevenSegment
import RPi.GPIO as GPIO
import speedtest
from transitions import Machine
from transitions.extensions.states import add_state_features, Timeout

from raspberrypi_utils.input_devices import Button
from raspberrypi_utils.output_devices import Buzzer, DigitalOutputDevice, LED
from raspberrypi_utils.utils import ReadConfigMixin


log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

log_filehandler = RotatingFileHandler('/var/log/speedtestreboot/speedtestreboot.log', maxBytes=1024**2, backupCount=100)
log_filehandler.setFormatter(log_formatter)
log_filehandler.setLevel(logging.INFO)

log_consolehandler = logging.StreamHandler()
log_consolehandler.setFormatter(log_formatter)
log_consolehandler.setLevel(logging.DEBUG)

log = logging.getLogger(__name__)
log.addHandler(log_filehandler)
log.addHandler(log_consolehandler)
log.setLevel(logging.DEBUG)

utils_log = logging.getLogger('raspberrypi_utils')
utils_log.setLevel(logging.DEBUG)
utils_log.addHandler(log_consolehandler)

transitions_log = logging.getLogger('transitions')
transitions_log.setLevel(logging.INFO)
transitions_log.addHandler(log_consolehandler)

sevenseg_log = logging.getLogger('SevenSegment')
sevenseg_log.setLevel(logging.INFO)
sevenseg_log.addHandler(log_consolehandler)


@add_state_features(Timeout)
class TimeoutMachine(Machine):
    pass


class SpeedTestRebooter(ReadConfigMixin, TimeoutMachine):
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
        self.router = DigitalOutputDevice(self.config['Main']['ROUTER_PIN'], initial_on=True, on_high_logic=False)
        self.modem = DigitalOutputDevice(self.config['Main']['MODEM_PIN'], initial_on=True, on_high_logic=False)
        self.normal_led = LED(self.config['Main']['NORMAL_LED_PIN'])
        self.slow_led = LED(self.config['Main']['SLOW_LED_PIN'])
        self.rebooting_led = LED(self.config['Main']['REBOOTING_LED_PIN'])
        self.button = Button(self.config['Main']['BUTTON_PIN'], self.button_pressed,
                             self.config['Main']['MANUAL_REBOOT_SECONDS'], self.button_held)
        self.buzzer = Buzzer(self.config['Main']['BUZZER_PIN'], 10000, self.config['Main']['QUIET_HOURS_RANGE'])
        self.download_speed = self.config['Main']['SLOW_SPEED']
        self.display = SevenSegment.SevenSegment(address=0x70)
        self.display.begin()
        self.to_normal()
        log.debug('Initialized')

    def check_speed(self):
        self.slow_led.off()
        self.normal_led.off()
        self.rebooting_led.on()
        s = speedtest.Speedtest()
        s.get_best_server()
        s.download()
        self.download_speed = s.results.download / 10**6
        self.display_speed()
        log.debug('Download speed = {:.1f} Mbps'.format(self.download_speed))
        self.update()

    def display_speed(self, clear=False):
        self.display.clear()
        if clear:
            self.display.write_display()
        else:
            self.display.print_float(self.download_speed, decimal_digits=1, justify_right=True)
            self.display.write_display()

    def sleep(self):
        minutes = (
            self.config['Main']['CHECK_INTERVAL_MINUTES']
            if self.can_go_normal()
            else self.config['Main']['CHECK_INTERVAL_MINUTES_AFTER_LOW']
        )
        sleep(minutes * 60.0)

    def can_go_normal(self):
        return self.download_speed >= self.config['Main']['SLOW_SPEED']

    def can_go_low(self):
        return not self.can_go_normal()

    def on_enter_low(self):
        self.display.set_blink(HT16K33.HT16K33_BLINK_1HZ)
        self.buzzer.stop()
        self.normal_led.off()
        self.rebooting_led.off()
        self.slow_led.on()

    def on_enter_normal(self):
        self.display.set_blink(HT16K33.HT16K33_BLINK_OFF)
        self.buzzer.stop()
        self.slow_led.off()
        self.rebooting_led.off()
        self.normal_led.on()

    def on_enter_warn_reboot(self):
        self.display.set_blink(HT16K33.HT16K33_BLINK_2HZ)
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
        self.display.set_blink(HT16K33.HT16K33_BLINK_OFF)
        self.rebooting_led.off()

    def reboot(self):
        log.warning('Rebooting')
        self.modem.off()
        self.router.off()
        sleep(self.config['Main']['REBOOT_DELAY_SECONDS'])
        self.modem.on()
        sleep(self.config['Main']['ROUTER_DELAY_SECONDS'])
        self.router.on()
        self.to_normal()

    def cleanup(self):
        self.buzzer.stop()
        self.normal_led.off()
        self.slow_led.off()
        self.display_speed(clear=True)
        GPIO.cleanup()
        log.debug('Shutdown')
