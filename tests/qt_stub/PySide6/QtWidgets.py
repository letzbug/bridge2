from ._stub import make_widgets_getattr
__getattr__ = make_widgets_getattr(__name__)
