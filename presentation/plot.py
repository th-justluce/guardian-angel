import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Polygon, Circle

# Set up the figure and axis
fig, ax = plt.subplots(figsize=(10, 8))
plt.tight_layout()
ax.set_xlim(-10, 10)
ax.set_ylim(-10, 10)
ax.set_aspect('equal')
ax.axis('off')  # Hide the axes

# Clean white background
fig.patch.set_facecolor('white')
ax.set_facecolor('white')

# Define initial positions and speeds
plane_pos = np.array([-8, 0])
plane_speed = 0.25
missile_pos = np.array([8, 8])  # Missile starts from top-right
missile_speed = 0.7

# Calculate interception time and point
delta_pos = plane_pos - missile_pos
delta_v = np.array([plane_speed, 0]) - missile_speed * delta_pos / np.linalg.norm(delta_pos)
t_intercept = np.linalg.norm(delta_pos) / np.linalg.norm(delta_v)
intercept_point = plane_pos + t_intercept * np.array([plane_speed, 0])

# Create the objects - now with just black outlines, no fill
def create_plane(pos, scale=0.5):
    # Plane shape (simplified for top-down view)
    plane_vertices = scale * np.array([
        [2, 0],    # Nose
        [0, 1],    # Right wing tip
        [-1, 0.5], # Right wing back
        [-1, 0.2], # Body right
        [-1.5, 0], # Tail
        [-1, -0.2],# Body left
        [-1, -0.5],# Left wing back
        [0, -1],   # Left wing tip
    ])
    # Shift to position
    plane_vertices = plane_vertices + pos.reshape(1, 2)
    return Polygon(plane_vertices, closed=True, fc='none', ec='black', 
                   lw=1.5, zorder=3)

def create_missile(pos, scale=0.25):
    # Missile body - simplified to a circle outline
    missile_body = Circle(pos, scale, fc='none', ec='red', 
                          lw=1.5, zorder=3)
    return missile_body

# Add a simple timer text
timer_text = ax.text(0.5, 0.95, '', transform=ax.transAxes, ha='center', va='top',
                    fontsize=12, color='black', family='monospace')

# Initialize the objects
plane = create_plane(plane_pos)
missile = create_missile(missile_pos)
ax.add_patch(plane)
ax.add_patch(missile)

# Animation update function
def update(frame):
    # Total frames for 6 seconds at 20 fps = 120 frames
    total_frames = 120
    impact_frame = 100  # Impact at 5 seconds
    
    if frame < impact_frame:
        # Approach phase
        progress = frame / impact_frame
        current_plane_pos = plane_pos + progress * (intercept_point - plane_pos)
        
        # Calculate missile position for this frame (leading to interception)
        missile_direction = (intercept_point - missile_pos) / np.linalg.norm(intercept_point - missile_pos)
        distance_covered = progress * np.linalg.norm(intercept_point - missile_pos)
        current_missile_pos = missile_pos + missile_direction * distance_covered
        
        # Update positions
        plane.set_xy(create_plane(current_plane_pos).get_xy())
        missile.set_center(current_missile_pos)
        
        # Calculate remaining time to impact (fixed at 6 seconds total animation)
        remaining_time = 5 - (frame / 20)  # 5 seconds until impact at frame 100
        timer_text.set_text(f"T-{remaining_time:.1f}s")
        
    else:
        # After impact - everything vanishes
        plane.set_alpha(0)
        missile.set_alpha(0)
        timer_text.set_text("")
    
    return plane, missile, timer_text

# Create animation - 6 seconds at 20fps = 120 frames
animation = FuncAnimation(fig, update, frames=120, interval=50, blit=True)

from matplotlib.animation import PillowWriter
animation.save('plane_missile_collision.gif', writer=PillowWriter(fps=20))

plt.show()
