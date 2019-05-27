from copy import copy
from threading import Lock
from typing import List, TYPE_CHECKING, TypeVar

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPaintEvent, QPainter, QPen, QPicture, QTransform, QBrush
from PyQt5.QtWidgets import QWidget

from Axis import ValueAxis, ValueBarAxis
from Base import ColorType, DrawConfig, DrawingCache, Orientation

if TYPE_CHECKING:
    from Base import DrawerBase

T = TypeVar("T")


def scale_from_mid(low, high, ratio):
    mid = (low + high) / 2
    scaled_range_2 = (high - low) / 2 * ratio
    return mid - scaled_range_2, mid + scaled_range_2


class ExtraDrawConfig(DrawConfig):

    def __init__(self):
        super().__init__()
        self.has_showing_data: bool = False


class BarChartWidget(QWidget):
    """
    用于管理二维平面图，目前只支持x坐标值为线性整数的图标。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.y_scale = 1.1
        self.plot_area_edge_color: "ColorType" = QColor(0, 0, 0)
        self.plot_area_edge_visible: bool = True
        padding = 80
        # 注意，当bottom和right为0时，最下边和最右边的边框会因为越界而不显示
        # padding: (left, top, buttom, right)
        self.paddings = [padding, padding, padding, padding]

        self.axis_x = ValueBarAxis(Orientation.HORIZONTAL)
        self.axis_y = ValueAxis(Orientation.VERTICAL)

        self._draw_config = ExtraDrawConfig()
        self._drawers: List["DrawerBase"] = []

        self._draw_config.begin = 0
        self._draw_config.end = 10

        self._repaint_lock = Lock()
        self._repaint_scheduled = False

    def add_drawer(self, drawer: "DrawerBase"):
        self._drawers.append(drawer)
        self.update()

    def set_x_range(self, begin: int, end: int):
        self._draw_config.begin, self._draw_config.end = begin, end
        self.update()

    def plot_area(self, config: "ExtraDrawConfig") -> "QRectF":
        """
        在UI坐标系中计算出绘制区域
        内部绘制函数无需调用该函数，查看config.output这个缓存的值即可
        """
        output: QRectF = QRectF(self.rect())
        paddings = self.paddings
        output2 = output.adjusted(paddings[0], paddings[1], -paddings[2], -paddings[3])
        return output2

    def drawer_to_ui(self, value: T, config: "ExtraDrawConfig" = None) -> T:
        """
        将value从drawer坐标系转到UI坐标系
        """
        if config is None:
            config = self._draw_config
        return config.drawing_cache.drawer_transform.map(value)

    #########################################################################
    # Re-implemented protected methods
    #########################################################################
    def paintEvent(self, event: "QPaintEvent"):
        # copy config: ensure config is not change while painting
        config: "ExtraDrawConfig" = copy(self._draw_config)

        self._prepare_painting(config)
        primary_painter = QPainter(self)
        primary_painter.setWorldMatrixEnabled(True)

        # 绘制坐标轴
        self._paint_axis(config, primary_painter)

        # 绘制所有注册了的序列
        self._paint_drawers(config, primary_painter)

        # 绘制图表边框
        self._paint_box_edge(config, primary_painter)

        # 结束
        primary_painter.end()
        self._draw_config = config
        event.accept()

    #########################################################################
    # Private methods
    #########################################################################
    def _paint_drawers(self, config: "ExtraDrawConfig", painter: "QPainter"):
        if config.has_showing_data:
            for i, s in enumerate(self._drawers):
                if s.has_data():
                    self._switch_painter_to_drawer_coordinate(painter, config)
                    self._paint_drawer(s, config, painter)
            self._switch_painter_to_ui_coordinate(painter)

    def _paint_drawer(self, drawer: "DrawerBase", config: "ExtraDrawConfig", painter: "QPainter"):
        # painter = QPainter(layer)
        painter.setPen(QPen(Qt.transparent))
        drawer.draw(copy(config), painter)

    def _should_paint_axis(self, axis):
        return axis and axis.axis_visible and (axis.label_visible or axis.grid_visible)

    def _paint_axis(self, config: "ExtraDrawConfig", painter: "QPainter"):
        axises = [i for i in (self.axis_x, self.axis_y) if i and self._should_paint_axis(i)]
        for axis in axises:
            axis.prepare_draw(copy(config))
        # painter = QPainter(layer)

        # first: grid
        if config.has_showing_data:
            painter.setBrush(QColor(0, 0, 0, 0))
            for axis in axises:
                if axis.grid_visible:
                    painter.setPen(QColor(axis.grid_color))
                    axis.draw_grid(copy(config), painter)

        # last: labels
        if config.has_showing_data:
            for axis in axises:
                if axis.label_visible:
                    painter.setBrush(QColor(0, 0, 0, 0))
                    painter.setPen(QColor(axis.label_color))
                    painter.setFont(axis.label_font)
                    painter.setBrush(QColor(0, 0, 0, 0))
                    painter.setPen(QColor(axis.label_color))
                    axis.draw_labels(copy(config), painter)

    def _paint_box_edge(self, config: "ExtraDrawConfig", painter: "QPainter"):
        if self.plot_area_edge_visible:
            painter.setBrush(QBrush(Qt.transparent))
            painter.setPen(QPen(QColor(self.plot_area_edge_color)))
            painter.drawRect(config.drawing_cache.plot_area)

    def _prepare_painting(self, config: "ExtraDrawConfig"):
        """
        提前计算一些在绘图时需要的数据
        """
        # get preferred y range
        has_showing_data = config.end - config.begin
        config.has_showing_data = has_showing_data

        if has_showing_data and self._drawers:
            preferred_configs = [s.prepare_draw(copy(config)) for s in self._drawers if s.has_data()]
            if preferred_configs:
                y_low = min(preferred_configs, key=lambda c: c.y_low).y_low
                y_high = max(preferred_configs, key=lambda c: c.y_high).y_high
            else:
                y_low, y_high = 0, 1

            # scale y range
            config.y_low, config.y_high = scale_from_mid(y_low, y_high, self.y_scale)

        # 一些给其他类使用的中间变量，例如坐标转化矩阵
        self._prepare_drawing_cache(config)

    def _prepare_drawing_cache(self, config: "ExtraDrawConfig"):
        """
        生成一个矩阵用以将painter的坐标系从UI坐标系调整为drawer坐标系
        这样painter中的x和y轴就正好对应数据的x和y了

        """
        # 从UI坐标系到drawer坐标系的转化矩阵的构造顺序恰好相反，假设目前为drawer坐标系
        # 将drawer坐标转化为UI坐标
        drawer_area = QRectF(config.begin,
                             config.y_low,
                             max(config.end - config.begin, 1),
                             max(config.y_high - config.y_low, 1),
                             )
        plot_area = self.plot_area(config)
        # 应用这个坐标转化
        transform = self._coordinate_transform(drawer_area, plot_area)

        # 去除padding对上下翻转的影响
        transform *= QTransform.fromTranslate(0, -plot_area.top())

        # 在UI坐标系中上下翻转图像
        transform *= QTransform.fromTranslate(0, -plot_area.height())
        transform *= QTransform().rotate(180, Qt.XAxis)

        # 恢复padding
        transform *= QTransform.fromTranslate(0, plot_area.top())

        # 保存一些中间变量
        drawing_cache = DrawingCache()
        drawing_cache.drawer_transform = transform
        drawing_cache.ui_transform = transform.inverted()[0]
        drawing_cache.drawer_area = drawer_area
        drawing_cache.plot_area = plot_area

        config.drawing_cache = drawing_cache

    def _switch_painter_to_drawer_coordinate(self, painter: "QPainter", config: "ExtraDrawConfig"):
        """
        将painter的坐标系从UI坐标系调整为drawer坐标系
        这样painter中的x和y轴就正好对应数据的x和y了
        """
        painter.setWorldTransform(config.drawing_cache.drawer_transform)

    def _switch_painter_to_ui_coordinate(self, painter: "QPainter"):
        painter.setWorldMatrixEnabled(False)

    def _coordinate_transform(self, input: QRectF, output: QRectF):
        rx, ry = output.width() / input.width(), output.height() / input.height()
        t = QTransform.fromTranslate(-input.left(), -input.top())
        t *= QTransform.fromScale(rx, ry)
        t *= QTransform.fromTranslate(output.left(), output.top())
        return t
