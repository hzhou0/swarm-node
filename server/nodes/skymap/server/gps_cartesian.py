"""
MIT License
Copyright (c) 2019 Michail Kalaitzakis
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import numpy as np
from scipy.spatial.transform import Rotation


class ENUCoordinateSystem:
    """
    Contains the algorithms to convert a gps signal (longitude, latitude, height)
    to a local cartesian ENU system and vice versa

    Use setENUorigin(lat, lon, height) to set the local ENU coordinate system origin
    Use gps2enu(lat, lon, height) to get the position in the local ENU system
    Use enu2gps(x_enu, y_enu, z_enu) to get the latitude, longitude and height
    """

    def __init__(self):
        # Geodetic System WGS 84 axes
        self.a = 6378137.0
        self.b = 6356752.314245
        self.a2 = self.a * self.a
        self.b2 = self.b * self.b
        self.e2 = 1.0 - (self.b2 / self.a2)
        self.e = self.e2 / (1.0 - self.e2)

        # Local ENU Origin
        self.latZero = None
        self.lonZero = None
        self.hgtZero = None
        self.xZero = None
        self.yZero = None
        self.zZero = None
        self.R = np.asmatrix(np.eye(3))

    def has_origin(self):
        return self.latZero is not None

    def set_enu_origin(self, lat, lon, height):
        # Save origin lat, lon, height
        self.latZero = lat
        self.lonZero = lon
        self.hgtZero = height

        # Get origin ECEF X,Y,Z
        origin = self.geo2ecef(self.latZero, self.lonZero, self.hgtZero)
        self.xZero = origin.item(0)
        self.yZero = origin.item(1)
        self.zZero = origin.item(2)
        self.oZero = np.array([[self.xZero], [self.yZero], [self.zZero]])

        # Build rotation matrix
        phi = np.deg2rad(self.latZero)
        lmd = np.deg2rad(self.lonZero)

        cPhi = np.cos(phi)
        cLmd = np.cos(lmd)
        sPhi = np.sin(phi)
        sLmd = np.sin(lmd)

        self.R[0, 0] = -sLmd
        self.R[0, 1] = cLmd
        self.R[0, 2] = 0.0
        self.R[1, 0] = -sPhi * cLmd
        self.R[1, 1] = -sPhi * sLmd
        self.R[1, 2] = cPhi
        self.R[2, 0] = cPhi * cLmd
        self.R[2, 1] = cPhi * sLmd
        self.R[2, 2] = sPhi

    def geo2ecef(self, lat, lon, height):
        phi = np.deg2rad(lat)
        lmd = np.deg2rad(lon)

        cPhi = np.cos(phi)
        cLmd = np.cos(lmd)
        sPhi = np.sin(phi)
        sLmd = np.sin(lmd)

        N = self.a / np.sqrt(1.0 - self.e2 * sPhi * sPhi)

        x = (N + height) * cPhi * cLmd
        y = (N + height) * cPhi * sLmd
        z = ((self.b2 / self.a2) * N + height) * sPhi

        return np.array([[x], [y], [z]])

    def ecef2enu(self, x, y, z):
        ecef = np.array([[x], [y], [z]])

        return self.R * (ecef - self.oZero)

    def gps2enu(self, lat, lon, height):
        ecef = self.geo2ecef(lat, lon, height)

        return self.ecef2enu(ecef.item(0), ecef.item(1), ecef.item(2))

    def ecef2gps(self, x, y, z):
        p = np.sqrt(x * x + y * y)
        q = np.arctan2(self.a * z, self.b * p)

        sq = np.sin(q)
        cq = np.cos(q)

        sq3 = sq * sq * sq
        cq3 = cq * cq * cq

        phi = np.arctan2(z + self.e * self.b * sq3, p - self.e2 * self.a * cq3)
        lmd = np.arctan2(y, x)
        v = self.a / np.sqrt(1.0 - self.e2 * np.sin(phi) * np.sin(phi))

        lat = np.rad2deg(phi)
        lon = np.rad2deg(lmd)
        h = (p / np.cos(phi)) - v

        return np.array([[lat], [lon], [h]])

    def enu2ecef(self, x, y, z):
        lmd = np.deg2rad(self.latZero)
        phi = np.deg2rad(self.lonZero)

        cPhi = np.cos(phi)
        cLmd = np.cos(lmd)
        sPhi = np.sin(phi)
        sLmd = np.sin(lmd)

        N = self.a / np.sqrt(1.0 - self.e2 * sLmd * sLmd)

        x0 = (self.hgtZero + N) * cLmd * cPhi
        y0 = (self.hgtZero + N) * cLmd * sPhi
        z0 = (self.hgtZero + (1.0 - self.e2) * N) * sLmd

        xd = -sPhi * x - cPhi * sLmd * y + cLmd * cPhi * z
        yd = cPhi * x - sPhi * sLmd * y + cLmd * sPhi * z
        zd = cLmd * y + sLmd * z

        return np.array([[x0 + xd], [y0 + yd], [z0 + zd]])

    def enu2gps(self, x, y, z):
        ecef = self.enu2ecef(x, y, z)

        return self.ecef2gps(ecef.item(0), ecef.item(1), ecef.item(2))


def create_transformation_matrix(x: float, y: float, z: float, yaw: float, pitch: float, roll: float, degrees=True):
    """
    Creates a 4x4 transformation matrix (extrinsic matrix) from translation and Euler angles.

    Parameters:
        :param x
        :param y
        :param z
            Translation components.
        :param pitch
        :param roll
        :param yaw
            Euler angles representing rotations around the axes.
        :param degrees
            If True, the provided angles are in degrees.

    Returns:
        extrinsic : numpy.ndarray
            4x4 transformation (extrinsic) matrix.
    """

    # Define the Euler angle order.
    # The choice of order ('xyz', 'zyx', etc.) depends on your application's convention.
    # In this example, we assume that the rotation is applied in the 'zyx' order:
    # first yaw (around Z), then pitch (around Y), then roll (around X).
    rotation = Rotation.from_euler("zyx", [yaw, pitch, roll], degrees=degrees)

    # Get the rotation matrix (3x3)
    R_mat = rotation.as_matrix()

    # Create the 4x4 transformation matrix initialized to identity
    extrinsic = np.eye(4)

    # Insert the rotation into the 3x3 upper-left submatrix
    extrinsic[:3, :3] = R_mat

    # Insert the translation vector into the matrix (last column)
    extrinsic[:3, 3] = np.array([x, y, z])

    return extrinsic


if __name__ == "__main__":
    coord = ENUCoordinateSystem()
    coord.set_enu_origin(45.0, 135.0, 0.0)
    print(coord.gps2enu(45.0, 135.0, 0.0))
    print(coord.gps2enu(45, 135, 1.0))
    print(create_transformation_matrix(1, 2, 3, 90, 256, -90))
