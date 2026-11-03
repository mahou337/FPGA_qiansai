"""OpenCV 3/4 contour signature normalization; no algorithm change."""
import cv2

def find_contours(*args, **kwargs):
    result = cv2.findContours(*args, **kwargs)
    if len(result) not in (2, 3):
        raise RuntimeError('Unexpected OpenCV findContours signature')
    return result[-2], result[-1]
