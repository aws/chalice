import warnings
try:
    from chalice.cdk.construct import Chalice
except ImportError:
    warnings.warn('Unable to import the Chalice CDK construct due to missing '
                  'dependencies.\nYou can install these by running '
                  "'pip install \"chalice[cdk]\"'")


__all__ = ['Chalice']
