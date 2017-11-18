from speedtestrebooter import SpeedTestRebooter


def main():
    rebooter = SpeedTestRebooter()
    try:
        while True:
            rebooter.check_speed()
            rebooter.sleep()
    finally:
        rebooter.cleanup()


if __name__ == '__main__':
    main()
