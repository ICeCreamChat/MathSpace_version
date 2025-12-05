from manim import *

class SphereIn3D(ThreeDScene):
    def construct(self):
        # 设置相机视角，确保三维效果清晰可见
        self.set_camera_orientation(phi=75 * DEGREES, theta=30 * DEGREES)
        
        # 创建三维坐标系
        axes = ThreeDAxes(
            x_range=[-4, 4, 1],
            y_range=[-4, 4, 1],
            z_range=[-4, 4, 1],
            x_length=8,
            y_length=8,
            z_length=8,
        )
        
        # 创建球体 - 位于坐标系原点，不旋转
        sphere = Sphere(
            radius=1.5,
            resolution=(24, 24),  # 适当的分辨率保证平滑度
            color=BLUE,
            fill_opacity=0.8,
        )
        # 默认已在原点，无需额外shift
        
        # 添加坐标系标签
        axes_labels = axes.get_axis_labels(
            x_label="x", y_label="y", z_label="z"
        )
        
        # 动画序列
        # 1. 显示坐标系
        self.play(Create(axes), Write(axes_labels))
        self.wait(0.5)
        
        # 2. 显示球体（使用FadeIn使出现更自然，且不旋转）
        self.play(FadeIn(sphere))
        self.wait(1)
        
        # 3. 保持相机静止，强调球体不旋转
        self.wait(3)