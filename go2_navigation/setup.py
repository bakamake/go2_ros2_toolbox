import os
from glob import glob
from setuptools import setup

package_name = 'go2_navigation'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml')),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools', 'pyyaml'],
    zip_safe=True,
    maintainer='andy-desktop-ubuntu',
    maintainer_email='zhuoan@stu.pku.edu.cn',
    description='Go2 navigation glue: Nav2 TCP bridge and standalone TCP client.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'nav2_tcp_bridge = go2_navigation.navigation_command_tcpbridge:main',
            'tcp_client_standalone = go2_navigation.tcp_client_standalone:main',
        ],
    },
)
