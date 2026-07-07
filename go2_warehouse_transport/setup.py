import os
from glob import glob
from setuptools import setup

package_name = 'go2_warehouse_transport'

setup(
    name=package_name,
    version='0.1.0',
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
    maintainer_email='zhuoan@stu.edu.cn',
    description=(
        'Go2 warehouse transport: autonomous pickup, transport and '
        'fixed-point placement of simulated payloads in a warehouse '
        'scenario. Wraps Nav2 with a PICKUP -> TRANSPORT -> PLACE '
        'state machine and exposes a TCP API for an external dispatcher.'
    ),
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'warehouse_transport_bridge = '
            'go2_warehouse_transport.warehouse_transport_bridge:main',
            'warehouse_demo_dispatcher = '
            'go2_warehouse_transport.warehouse_demo_dispatcher:main',
        ],
    },
)
