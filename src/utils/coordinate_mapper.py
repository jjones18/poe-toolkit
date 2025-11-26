"""
Stash grid coordinate mapping.
"""


class StashGridMapper:
    """Maps PoE API stash coordinates (x, y) to screen pixels."""
    
    def __init__(self, offset_x=18, offset_y=160, cell_size=53):
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.cell_size = cell_size

    def get_rect(self, grid_x: int, grid_y: int, width: int = 1, height: int = 1):
        """Returns (x, y, w, h) for a given item position."""
        pixel_x = self.offset_x + (grid_x * self.cell_size)
        pixel_y = self.offset_y + (grid_y * self.cell_size)
        pixel_w = width * self.cell_size
        pixel_h = height * self.cell_size
        return (pixel_x, pixel_y, pixel_w, pixel_h)

    def calculate_from_points(self, p1: tuple, p2: tuple, is_quad: bool = False):
        """
        Calculates offset and cell_size from calibration points.
        p1: Top-Left corner of first cell
        p2: Bottom-Right corner of last cell
        """
        grid_dim = 24 if is_quad else 12
        
        total_w = p2[0] - p1[0]
        total_h = p2[1] - p1[1]
        
        cell_w = total_w / grid_dim
        cell_h = total_h / grid_dim
        
        self.cell_size = int((cell_w + cell_h) / 2)
        self.offset_x = int(p1[0])
        self.offset_y = int(p1[1])
        
        return self.offset_x, self.offset_y, self.cell_size

