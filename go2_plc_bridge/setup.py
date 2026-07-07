import os
from glob import glob
from setuptools import setup

package_name = 'go2_plc_bridge'

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
    maintainer_email='zhuoan@stu.pku.edu.cn',
    description=(
        'Glue nodes mirroring /home/bakamake/Downloads/1.py inside ROS2: '
        'PLC I128.0 -> SSH standup/standown + optional UDP trigger/feedback.'
    ),
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'plc_dog_bridge = go2_plc_bridge.plc_dog_bridge_node:main',
            'udp_trigger = go2_plc_bridge.udp_trigger_node:main',
            'udp_feedback = go2_plc_bridge.udp_feedback_node:main',
        ],
    },
)
