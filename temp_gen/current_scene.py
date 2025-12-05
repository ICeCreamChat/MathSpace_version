from manim import *

class StaticSphereIn3D(ThreeDScene):
    def construct(self):
        # 初始相机视角 - 与原始代码保持一致
        self.set_camera_orientation(
            phi=75 * DEGREES,
            theta=30 * DEGREES,
            zoom=1.0
        )
        
        # 创建三维坐标系
        axes = ThreeDAxes(
            x_range=[-4, 4, 1],
            y_range=[-4, 4, 1],
            z_range=[-4, 4, 1],
            x_length=8,
            y_length=8,
            z_length=8,
        )
        
        # 创建球体
        sphere = Sphere(
            radius=1.5,
            resolution=(30, 30),
            color=BLUE,
            fill_opacity=0.6
        )
        sphere.set_stroke(color=BLUE_E, width=2)
        
        # 创建坐标轴标签 - 使用always_redraw确保标签始终正确显示
        x_label = always_redraw(lambda: 
            MathTex("x", color=RED, font_size=28)
            .next_to(axes.x_axis.get_end(), RIGHT, buff=0.1)
        )
        y_label = always_redraw(lambda: 
            MathTex("y", color=GREEN, font_size=28)
            .next_to(axes.y_axis.get_end(), UP, buff=0.1)
        )
        z_label = always_redraw(lambda: 
            MathTex("z", color=BLUE, font_size=28)
            .next_to(axes.z_axis.get_end(), UP, buff=0.1)
        )
        
        # 创建球体标签 - 固定在球体上方
        sphere_label = always_redraw(lambda: 
            MathTex(r"S^2", color=WHITE, font_size=36)
            .next_to(sphere.get_center(), UP + RIGHT, buff=0.3)
        )
        
        # 动画序列
        # 1. 显示坐标系
        self.play(Create(axes), run_time=1.5)
        self.wait(0.3)
        
        # 2. 显示坐标轴标签
        self.play(
            Write(x_label),
            Write(y_label),
            Write(z_label)
        )
        self.wait(0.3)
        
        # 3. 显示球体
        self.play(Create(sphere), run_time=1.5)
        self.wait(0.3)
        
        # 4. 显示球体标签
        self.play(Write(sphere_label))
        self.wait(0.5)
        
        # 5. 向下移动相机视角以显示完整的三个坐标轴
        # 使用move_camera动画展示视角变化过程
        self.move_camera(
            phi=60 * DEGREES,      # 减小phi角度使视角更向下
            theta=-45 * DEGREES,   # 调整theta以显示完整的坐标系
            zoom=0.8,              # 稍微缩小以确保所有内容在视野内
            run_time=3
        )
        self.wait(1)
        
        # 6. 最终停留
        self.wait(2)