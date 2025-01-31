import math
import unittest

from matplotlib import pyplot as plt


class MyTestCase(unittest.TestCase):
    def test_3phase_decode(self):
        period = 2 ** 8
        encoded = []
        for _i in range(period):
            i = (_i - 127) * math.tau / period
            I1 = round((period - 1) * 0.5 * (1 + math.cos(i - 2 * math.pi / 3)))
            I2 = round((period - 1) * 0.5 * (1 + math.cos(i)))
            I3 = round((period - 1) * 0.5 * (1 + math.cos(i + 2 * math.pi / 3)))
            encoded.append([I1, I2, I3])
        y = []
        for I1, I2, I3 in encoded:
            phi = round((math.atan2(math.sqrt(3) * (I1 - I3), (2 * I2 - I1 - I3))) / math.tau * period) + 127
            y.append(phi)
        plt.plot(y)
        plt.show()
        self.assertEqual(y, list(range(256)))


if __name__ == '__main__':
    unittest.main()
