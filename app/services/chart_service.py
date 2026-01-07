"""
Chart generation service for creating bag statistics images.
Used for attaching visual summaries to Zoho purchase receives.
"""
import io
import logging
from typing import Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Color constants (matching UI colors)
INDIGO_600 = (79, 70, 229)  # #4F46E5 - Received
PURPLE_600 = (147, 51, 234)  # #9333EA - Packaged
WHITE = (255, 255, 255)
GRAY_100 = (243, 244, 246)
GRAY_600 = (75, 85, 99)
GRAY_800 = (31, 41, 55)


def format_number(num: int) -> str:
    """Format a number with comma separators."""
    return f"{num:,}"


def generate_bag_chart_image(bag_label_count: int, packaged_count: int) -> bytes:
    """
    Generate a PNG image showing bag statistics (received vs packaged counts).
    
    Creates a visual representation with two stat boxes:
    - Received (indigo): shows bag_label_count
    - Packaged (purple): shows packaged_count
    
    Args:
        bag_label_count: The count from the bag label (received tablets)
        packaged_count: The calculated packaged tablet count from submissions
        
    Returns:
        PNG image as bytes, or empty bytes if generation fails
    """
    if not PIL_AVAILABLE:
        logger.error("PIL/Pillow not available for chart generation")
        return b''
    
    try:
        # Image dimensions
        width = 400
        height = 180
        padding = 20
        box_gap = 20
        box_width = (width - 2 * padding - box_gap) // 2
        box_height = 120
        
        # Create image with light gray background
        image = Image.new('RGB', (width, height), GRAY_100)
        draw = ImageDraw.Draw(image)
        
        # Try to load a font, fall back to default if not available
        try:
            # Try to use a system font
            title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
            number_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
            label_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
        except (OSError, IOError):
            try:
                # Try alternative system fonts
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                number_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
                label_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except (OSError, IOError):
                # Fall back to default font
                title_font = ImageFont.load_default()
                number_font = ImageFont.load_default()
                label_font = ImageFont.load_default()
        
        # Draw title
        title = "Bag Statistics"
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_width) // 2, 10), title, fill=GRAY_800, font=title_font)
        
        # Box positions
        box_y = 40
        received_box_x = padding
        packaged_box_x = padding + box_width + box_gap
        
        # Draw Received box (indigo)
        _draw_stat_box(
            draw,
            x=received_box_x,
            y=box_y,
            width=box_width,
            height=box_height,
            bg_color=INDIGO_600,
            value=bag_label_count,
            label="Received",
            number_font=number_font,
            label_font=label_font
        )
        
        # Draw Packaged box (purple)
        _draw_stat_box(
            draw,
            x=packaged_box_x,
            y=box_y,
            width=box_width,
            height=box_height,
            bg_color=PURPLE_600,
            value=packaged_count,
            label="Packaged",
            number_font=number_font,
            label_font=label_font
        )
        
        # Save to bytes
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        buffer.seek(0)
        
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Error generating bag chart image: {e}")
        return b''


def _draw_stat_box(
    draw: 'ImageDraw.Draw',
    x: int,
    y: int,
    width: int,
    height: int,
    bg_color: Tuple[int, int, int],
    value: int,
    label: str,
    number_font,
    label_font
) -> None:
    """
    Draw a rounded stat box with value and label.
    
    Args:
        draw: PIL ImageDraw object
        x, y: Top-left position
        width, height: Box dimensions
        bg_color: Background color tuple (R, G, B)
        value: Numeric value to display
        label: Text label below the value
        number_font: Font for the number
        label_font: Font for the label
    """
    # Draw rounded rectangle (approximation with regular rectangle + corners)
    corner_radius = 10
    
    # Draw main rectangle
    draw.rounded_rectangle(
        [x, y, x + width, y + height],
        radius=corner_radius,
        fill=bg_color
    )
    
    # Format the number with commas
    value_str = format_number(value)
    
    # Calculate text positions (center aligned)
    value_bbox = draw.textbbox((0, 0), value_str, font=number_font)
    value_width = value_bbox[2] - value_bbox[0]
    value_height = value_bbox[3] - value_bbox[1]
    
    label_bbox = draw.textbbox((0, 0), label, font=label_font)
    label_width = label_bbox[2] - label_bbox[0]
    
    # Vertical spacing
    total_text_height = value_height + 8 + 16  # number + gap + label
    start_y = y + (height - total_text_height) // 2
    
    # Draw value
    value_x = x + (width - value_width) // 2
    draw.text((value_x, start_y), value_str, fill=WHITE, font=number_font)
    
    # Draw label
    label_x = x + (width - label_width) // 2
    label_y = start_y + value_height + 8
    draw.text((label_x, label_y), label, fill=WHITE, font=label_font)

