from setuptools import setup, find_packages

with open("README.md") as f:
    long_description = f.read()

setup(
    name="tg_and_rental",
    version="0.0.1",
    description="TG and Rental App for ERPNext",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="you@example.com",
    license="MIT",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=["frappe"],
)
