from setuptools import setup, find_packages

setup(
    name="homgar-homeassistant",
    version="1.1.0",
    description="Home Assistant integration for HomGar irrigation devices (forked from Remboooo/homgarapi)",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Mateusz Mejsner",
    author_email="mateuszmejsner@gmail.com",
    url="https://github.com/macher91/homgar-homeassistant",
    packages=find_packages(),
    install_requires=[
        "requests>=2.0.0",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Home Automation",
    ],
    python_requires=">=3.9",
)