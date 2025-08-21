# This is a sample Python script.
# import network_process
# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
import geopandas as gpd
import data_level1
import data_level2
import data_level3
import tkinter as tk
from tkinter import ttk  # 导入 ttk 模块，用于 Progressbar
from tkinter import filedialog
from tkinter import messagebox
import os  # 用于检查文件是否存在等操作
import json
import logging

# --- 1. 初始的、临时的日志配置 ---
# 这是一个简单的控制台日志，用于捕获早期或配置前的日志
logging.basicConfig(
    level=logging.INFO,  # 默认级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # 默认输出到控制台
    ]
)
# 获取根日志记录器，或你将使用的主要记录器
logger = logging.getLogger(__name__)
logger.info("程序启动：正在初始化临时日志记录器（输出到控制台）。")


# 2. 独立的日志配置函数
def configure_logging_from_json(json_config_path):
    """
    读取 JSON 配置文件，并根据其中的设置重新配置日志记录器。
    这个函数是核心的日志配置逻辑，可以被任何部分调用。
    """
    root_logger = logging.getLogger()  # 获取根日志记录器，我们操作它来改变全局日志行为

    # 清除所有现有的处理器，防止重复输出或多余的控制台输出
    # 这一步非常关键，确保旧的处理器被移除
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()  # 必须关闭文件句柄，释放资源

    try:
        with open(json_config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        log_directory = config['log']['path']
        log_filename = config['log']['log_filename']
        log_level_str = config['log']['log_level']
        file_mode = config['log']['file_mode']

        numeric_log_level = getattr(logging, log_level_str, logging.INFO)

        # 确保日志目录存在
        if not os.path.exists(log_directory):
            os.makedirs(log_directory)

        full_log_path = os.path.join(log_directory, log_filename)

        # 设置根记录器的级别
        root_logger.setLevel(numeric_log_level)

        # 创建一个 FileHandler 来输出到文件
        file_handler = logging.FileHandler(full_log_path, mode=file_mode, encoding='utf-8')
        file_handler.setLevel(numeric_log_level)  # 文件处理器本身的级别

        # 定义格式化器
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)

        # 将 FileHandler 添加到根记录器
        root_logger.addHandler(file_handler)

        logger.info(f"日志系统已根据配置文件 '{json_config_path}' 重新配置。")
        logger.info(f"所有日志将输出到: {full_log_path}")
        return True  # 表示配置成功

    except FileNotFoundError:
        root_logger.addHandler(logging.StreamHandler())  # 重新添加控制台输出
        root_logger.warning(f"错误: 找不到配置文件 '{json_config_path}'。日志将继续输出到控制台。")
        return False
    except json.JSONDecodeError:
        root_logger.addHandler(logging.StreamHandler())
        root_logger.error(f"错误: 配置文件 '{json_config_path}' 格式不正确。日志将继续输出到控制台。")
        return False
    except Exception as e:
        root_logger.addHandler(logging.StreamHandler())
        root_logger.critical(f"重新配置日志时发生未知错误: {e}。日志将继续输出到控制台。")
        return False


# ！！！！！！UI界面初始化
class FileProcessingApp:
    def __init__(self, master):
        self.master = master
        master.title("电子地图数据智能处理")
        master.geometry("650x450")  # 设置窗口初始大小
        # 用于存储不同任务页面的Frame实例
        self.task_frames = {}
        self.current_task_frame = None

        # 创建顶部概念
        # ---1顶部容器---
        self.top_bar_frame = tk.Frame(master, bd=2, relief="groove", bg="white")
        self.top_bar_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        # tk.Label(self.top_bar_frame, text="我的应用程序", font=('Arial', 16, 'bold'), bg="#DDEEFF").pack(side=tk.LEFT,padx=10)
        # 顶部Notebook
        self.notebook_tabs = ttk.Notebook(self.top_bar_frame)
        self.notebook_tabs.pack(side=tk.LEFT, padx=10, pady=5)
        # Tab放顶部离左侧有一定距离，大概是button所占位置
        # 其他Tab页面
        # Tab 页内容
        self.tab1_dummy_frame = tk.Frame(self.notebook_tabs)  # 这是一个空 Frame，只用于 Notebook 的 add 方法
        self.notebook_tabs.add(self.tab1_dummy_frame, text="年度更新")
        self.tab2_dummy_frame = tk.Frame(self.notebook_tabs)
        self.notebook_tabs.add(self.tab2_dummy_frame, text="过程处理")

        # 绑定 Tab 切换事件，当 Tab 改变时，更新中间右侧区域的内容，_on_tab_changed就是方法
        self.notebook_tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # --- 2. 中间内容容器 (Middle Content Frame) ---
        self.middle_content_frame = tk.Frame(master, padx=10, pady=5)
        self.middle_content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 配置 Middle Content Frame 的 grid 布局，实现左右分栏
        self.middle_content_frame.grid_columnconfigure(0, weight=0)  # 左侧列不随窗口拉伸
        self.middle_content_frame.grid_columnconfigure(1, weight=1)  # 右侧列随窗口拉伸
        self.middle_content_frame.grid_rowconfigure(0, weight=1)  # 行随窗口拉伸

        # --- 2.1. 左侧固定面板 (Fixed Left Panel Frame) ---
        self.left_panel_frame = tk.Frame(self.middle_content_frame, bd=2, relief="ridge", width=60, bg="#F0F0F0")
        self.left_panel_frame.grid(row=0, column=0, sticky="nswe", padx=(0, 6))
        self.left_panel_frame.pack_propagate(False)  # 阻止子控件改变 Frame 的大小

        # ---2.1选择btn---
        selected_option = tk.StringVar(value="路网")
        radio_road = tk.Radiobutton(self.left_panel_frame, text="路网", variable=selected_option, value="路网", command=lambda: self._show_task_page("路网"))
        radio_water = tk.Radiobutton(self.left_panel_frame, text="水系", variable=selected_option, value="水系", command=lambda: self._show_task_page("水系"))
        radio_road.pack(anchor=tk.W)
        radio_water.pack(anchor=tk.W)

        # --- 2.2. 右侧内容显示 Frame (Content Display Frame) ---
        # 这个 Frame 会动态加载不同的任务界面
        self.content_display_frame = tk.Frame(self.middle_content_frame, bd=2, relief="flat", bg="white")
        self.content_display_frame.grid(row=0, column=1, sticky="nswe")

        # --- 3. 底部信息容器 (Bottom Info Frame) ---
        self.bottom_info_frame = tk.Frame(master, bd=1, relief="sunken", bg="#E0E0E0")
        self.bottom_info_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
        self.bottom_info_frame.grid_columnconfigure(1, weight=1)

        tk.Label(self.bottom_info_frame, text="配置信息", font=('Arial', 9, 'bold'), bg="#E0E0E0").grid(row=0, column=0,padx=5, pady=2,sticky="w")


        # # 进度条
        # # --- 进度条 (不确定模式) ---用自定义样式
        # self.progress_label = tk.Label(self.bottom_info_frame, text="处理状态:")
        # self.progress_label.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
        #
        # # mode="indeterminate" 是关键，表示不确定模式
        # self.progress_bar = ttk.Progressbar(self.bottom_info_frame, orient="horizontal", length=300, mode="indeterminate")
        # self.progress_bar.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="ew")

        # --- 初始化并显示第一个任务页面 ---
        self._create_task_pages()
        self._show_task_page("路网")  # 默认显示第一个Tab的内容

        # # 结束按钮
        # self.exit_button = tk.Button(main_frame, text="退出", command=master.quit)
        # self.exit_button.pack(pady=10)
        logger.info("UI 界面初始化完成。")

    def _create_task_pages(self):
        """创建所有任务界面的 Frame 实例，但不立即显示。"""
        # Task 1: 路网页面
        self.task_frames['路网'] = ttk.Frame(self.content_display_frame, padding="10")
        self._setup_roads_page(self.task_frames['路网'])
        #Task2:水系显示页面
        self.task_frames['水系'] = ttk.Frame(self.content_display_frame, padding="10")
        self._setup_rivers_page(self.task_frames['水系'])
        #Task3:年度更新


    def _show_task_page(self, task_name):
        """显示指定名称的任务页面，隐藏其他页面。"""
        if self.current_task_frame:
            self.current_task_frame.pack_forget()  # 隐藏当前显示的 Frame

        new_frame = self.task_frames.get(task_name)
        if new_frame:
            new_frame.pack(fill=tk.BOTH, expand=True)  # 显示新的 Frame
            self.current_task_frame = new_frame
            logger.info("成功切换到当前标签")
        else:
            logger.error("切换到标签失败，或标签页不存在")

    # 通过给标签绑定事件，读取当前是什么
    def _on_tab_changed(self, event):
        """当顶部 Notebook 的 Tab 切换时调用。"""
        selected_tab_index = self.notebook_tabs.index(self.notebook_tabs.select())
        selected_tab_name = self.notebook_tabs.tab(selected_tab_index, "text")
        self._show_task_page(selected_tab_name)

    # ---任务页面的具体布局方法---
    def _setup_roads_page(self, parent_frame):
        # 设计路网处理界面样式
        """设置文件处理页面（作为中间右侧内容）"""
        parent_frame.grid_columnconfigure(1, weight=1)
        tk.Label(parent_frame, text="路网数据处理", font=('Arial', 12, 'bold')).grid(row=0, column=0,columnspan=3, pady=10)

        tk.Label(parent_frame, text="输入文件:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        # 为文件处理标签页创建独立的 Entry
        self.file_processing_input_entry = tk.Entry(parent_frame, width=50)
        self.file_processing_input_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        # 绑定到独立的浏览方法
        tk.Button(parent_frame, text="选择文件", command=self.browse_file_for_processing).grid(row=1, column=2, padx=5, pady=5)

        tk.Label(parent_frame, text="一阶段结果输出目录:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.output_entry = tk.Entry(parent_frame, width=50)
        self.output_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        tk.Button(parent_frame, text="选择目录", command=lambda: self.browse_output_directory(self.output_entry)).grid(row=2, column=2, padx=5, pady=5)

        tk.Label(parent_frame, text="二阶段结果输出目录:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.output_entry1 = tk.Entry(parent_frame, width=50)
        self.output_entry1.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
        tk.Button(parent_frame, text="选择目录", command=lambda: self.browse_output_directory(self.output_entry1)).grid(row=3, column=2, padx=5, pady=5)

        self.process_button = tk.Button(parent_frame, text="开始处理", command=self.process_all_files)
        self.process_button.grid(row=4, column=0, columnspan=3, pady=10)

    # 水系的页面----具体情况去设计，但大致和roads差不多，不过要把读取文件方法做两个
    def _setup_rivers_page(self,parent_frame):
        # 设计水系处理界面样式
        """设置文件处理页面（作为中间右侧内容）"""
        # 设计路网处理界面样式
        """设置水系处理页面（内容）"""
        parent_frame.grid_columnconfigure(1, weight=1)
        tk.Label(parent_frame, text="水系数据处理", font=('Arial', 12, 'underline')).grid(row=0, column=0, columnspan=3, pady=10)

    def browse_file_for_processing(self):
        """
        打开文件选择对话框，并将选定的文件路径填充到指定索引的文本框。
        """
        file_path = filedialog.askopenfilename(
            title=f"选择文件...", # 对话框标题
            filetypes=[
                ("所有文件", "*.*"),
                ("文本文件", "*.txt"),
                ("CSV 文件", "*.csv"),
                ("Excel 文件", "*.xlsx *.xls")
            ]
        )
        if file_path:
            self.file_processing_input_entry.delete(0, tk.END)
            self.file_processing_input_entry.insert(0, file_path)
            #日志文件操作
            logger.info(f"用户通过 UI 选择了配置文件: {file_path}")
            # 调用外部的日志配置函数
            success = configure_logging_from_json(file_path)
            if success:
                logger.info(f"日志配置设置加载成功")
            else:
                logger.info(f'日志配置失败')

    def browse_output_directory(self, entry_widget):
        """打开“另存为”对话框，获取输出文件路径。"""
        file_path = filedialog.asksaveasfilename(
            title="保存输出文件为...",
            defaultextension=".txt",  # 默认文件扩展名
            filetypes=[
                ("文本文件", "*.txt"),
                ("CSV 文件", "*.csv"),
                ("Excel 文件", "*.xlsx"),
                ("所有文件", "*.*")
            ]
        )
        if file_path:
            # 清除 Entry 框当前内容，并插入新路径
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, file_path)
            # self.output_entry.delete(0, tk.END)
            # self.output_entry.insert(0, file_path)
            # # 加上第二阶段的情况
            # self.output_entry1.delete(0, tk.END)
            # self.output_entry1.insert(0, file_path)
            # logger.info("输出文件路径加载成功")

    # 后台数据处理函数，此函数在单独的线程运行---这是处理路网的
    def process_all_files(self):
        """
        这个方法是你的 Python 程序的核心文件处理逻辑所在。
        它将从 self.file_path_var 中获取json文件的路径，并进行操作。
        """
        # 从 StringVar 中获取实际的文件路径字符串
        # .get() 方法获取 StringVar 的当前值
        selected_file_path = self.file_processing_input_entry.get()

        # 过滤掉空的路径（用户未选择的槽位）以及不存在的文件
        actual_files_to_process = selected_file_path

        # 输出文件路径处理
        # 2. 获取输出文件路径并进行验证
        output_path = self.output_entry.get()
        if not output_path:
            messagebox.showwarning("验证失败", "请指定输出文件路径。")
            return

        # 确认输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                messagebox.showerror("错误", f"无法创建输出目录: {output_dir}\n错误: {e}")
                return

        # # 新加入的output_path
        # output_path1 = self.output_entry1.get()
        # if not output_path1:
        #     messagebox.showwarning("验证失败", "请指定输出文件路径。")
        #     return
        #
        # # 确认输出目录存在pyinstaller your_script.spec
        # output_dir = os.path.dirname(output_path1)
        # if output_dir and not os.path.exists(output_dir):
        #     try:
        #         os.makedirs(output_dir)
        #     except Exception as e:
        #         messagebox.showerror("错误", f"无法创建输出目录: {output_dir}\n错误: {e}")
        #         return

        messagebox.showinfo("处理开始", f"将处理文件。请查看控制台输出或等待结果...")

        print("\n--- 开始处理文件 ---")
        # 读取数据时的相应的层名 layer_name1--L7-10;2--L11-L12;3--L13-L14；4--L15-L17;layer_name是待处理数据数据
        # 读入的文件是json
        try:
            with open(actual_files_to_process, 'r', encoding='utf-8') as f:
                config = json.load(f)

            path_gis = config['lrdl_annual']['items'][0]['gdb_path']
            path_cart = config['lrdl_carto']['gdb_path']
            # 要处理的新数据--！！！！注意这里最重要的是feature_class，其他像是dataset这种gpd库是不会读取这个层级概念而是直接找class
            feature_dataset = config['lrdl_annual']['items'][0]['feature_dataset']
            feature_class = config['lrdl_annual']['items'][0]['feature_class']
            layer_name = f"{feature_dataset}/{feature_class}"

            # L7_L10
            feature_dataset1 = config['lrdl_carto']['items'][0]['feature_dataset']
            feature_class1 = config['lrdl_carto']['items'][0]['feature_class']
            layer_name1 = f"{feature_dataset1}/{feature_class1}"
            #L11_L12
            feature_dataset2 = config['lrdl_carto']['items'][1]['feature_dataset']
            feature_class2 = config['lrdl_carto']['items'][1]['feature_class']
            layer_name2 = f"{feature_dataset2}/{feature_class2}"
            # L13_L14
            feature_dataset3 = config['lrdl_carto']['items'][2]['feature_dataset']
            feature_class3 = config['lrdl_carto']['items'][2]['feature_class']
            layer_name3 = f"{feature_dataset3}/{feature_class3}"
            # L15_L17
            feature_dataset4 = config['lrdl_carto']['items'][3]['feature_dataset']
            feature_class4 = config['lrdl_carto']['items'][3]['feature_class']
            layer_name4 = f"{feature_dataset4}/{feature_class4}"

            #开始读取数据
            # 1--L7-L10
            layer1 = gpd.read_file(path_cart, layer=feature_class1)
            # 2--L11-L12
            layer2 = gpd.read_file(path_cart, layer=feature_class2)
            # 3--L13-L14
            layer3 = gpd.read_file(path_cart, layer=feature_class3)
            # 4--L15-L17
            layer4 = gpd.read_file(path_cart, layer=feature_class4)
            # 读取待处理的新数据
            layer_read = gpd.read_file(path_gis, layer=feature_class)
            # 拷贝数据
            layer_new = layer_read.copy()

            # 为保证后续cover的使用，将数据都转换成投影坐标的
            target_crs = "EPSG:4540"
            # 数据做投影
            layer_new_proj = layer_new.to_crs(target_crs)
            layer1_proj = layer1.to_crs(target_crs)
            layer2_proj = layer2.to_crs(target_crs)
            layer3_proj = layer3.to_crs(target_crs)
            layer4_proj = layer4.to_crs(target_crs)

            # print(layer_new_proj.geometry)
            # print(layer1.geometry)

            # 为数据添加字段;assign会返回一个新的GeoDataFrame，不是修改原来的
            print("\n--- 使用 .assign() 添加字段 ---")
            lrdl_backup = layer_new_proj.assign(
                NAME="",
                L7='2',
                L8='2',
                L9='2',
                L10='2',
                code2_1="",
                symbol2_1="",
                L11='2',
                L12='2',
                L13='2',
                L14='2',
                code2_2="",
                symbol2_2="",
                L15='2',
                L16='2',
                L17='2',
                code2_3="",
                symbol2_3="",
                BZ=""

            )
            # 将assign添加的列按照规定的顺序出现
            existing_cols = layer_new_proj.columns.tolist()
            new_cols_in_order = ['NAME', 'L7', 'L8', 'L9', 'L10', 'code2_1', 'symbol2_1', 'L11', 'L12', 'L13', 'L14', 'code2_2', 'symbol2_2', 'L15', 'L16', 'L17', 'code2_3', 'symbol2_3', 'BZ']

            # 构建最终的列顺序
            final_column_order = existing_cols + new_cols_in_order
            # 按顺序拍好新加入列的df数据,lrdl_backup是投影坐标数据==lrdl_final是投影坐标数据
            lrdl_final = lrdl_backup[final_column_order]
            # 给字段占位
            lrdl_final.loc[0, 'BZ'] = "这是一段用来占位的文字"
            # 查找是否有相应需要的字段
            print(f"DEBUG: Columns before error: {lrdl_final.columns}")

            # 进入具体实现covers环节
            # 先做缓冲区，保证可以选上
            # 第1级distance
            buffer_distance1 = 10
            # 第2级distance
            buffer_distance2 = 3
            # 第3级的distance
            buffer_distance3 = 2  # 示例：，请根据实际地图单位调整

            logger.info("执行数据处理逻辑。")
            # 对L7-L10处理
            data_level1.data_level_1(layer1_proj, lrdl_final, buffer_distance1)
            # 对11-12层进行处理
            data_level2.data_level_2(layer2_proj, lrdl_final, buffer_distance2)
            # 对13-14层进行处理
            data_level2.data_level_3(layer3_proj, lrdl_final, buffer_distance2)
            # 对L15-L17层数据进行处理
            data_level3.data_level_4(layer4_proj, lrdl_final, buffer_distance3)

            # # 二阶段处理，后续测试工作完成后加入
            # gdf_process_sec = network_process.network(lrdl_final)

            # 输出
            # print("一阶段结果，二阶段会再copy一次gdf不会直接修改一阶段的gdf")
            print(lrdl_final[['L7', 'L8', 'L9', 'L10', 'L11', 'L12', 'L13', 'L14', 'L15', 'L16', 'L17']].head(15))
            try:
                lrdl_final.to_file(output_path, encoding='utf-8')
                # gdf_process_sec.to_file(output_path1)
                print(f"数据已成功输出，使用 UTF-8 编码。")
                print("请注意检查：")
                print("  - Shapefile 包含: .shp, .shx, .dbf, .prj 等多个文件。")
                print("  - 列名 'name' 可能被截断为 '名称'。")
                print("  - 列名 'value_long_name' 可能被截断为 '长值'。")
                print(
                    "  - 如果原始 GeoDataFrame 包含混合几何类型，输出的 Shapefile 只会包含其中一种类型（通常是第一行遇到的类型），其他类型的数据可能被忽略。建议按几何类型分别输出。")
                logger.info(f"处理完成")
                messagebox.showinfo("处理完成", "所有文件处理完毕！")
            except Exception as e:
                logger.info(f"输出 Shapefile 时发生错误: {e}")
                messagebox.showinfo("输出 Shapefile 时发生错误")

            # 例如：
            # with open(labels_file, 'r') as lf:
            #     data = lf.read()
            # print(f"已读取标签文件部分内容: {data[:100]}...")

        except FileNotFoundError:
            logger.error(f"错误: 配置文件未找到在 '{actual_files_to_process}'")
            print(f"错误: 配置文件未找到在 '{actual_files_to_process}'")
            messagebox.showinfo("配置文件未找到")
        except KeyError as e:
            logger.error(f"错误: JSON 配置中缺少键: {e}. 请检查 '{actual_files_to_process}' 文件结构。")
            print(f"错误: JSON 配置中缺少键: {e}. 请检查 '{actual_files_to_process}' 文件结构。")
            messagebox.showinfo("JSON 配置中缺少键:")
        except json.JSONDecodeError:
            logger.error(f"错误: 无法解析 JSON 文件 '{actual_files_to_process}'. 请检查其语法。")
            print(f"错误: 无法解析 JSON 文件 '{actual_files_to_process}'. 请检查其语法。")
            messagebox.showinfo("无法解析 JSON 文件,请检查其语法")
        except Exception as e:
            logger.error(f"发生未知错误: {e}")
            print(f"发生未知错误: {e}")
            messagebox.showinfo("发生未知的错误")
            # self.master.after(0, lambda: self._process_error(e))


# def read_file(gdb_path,layer_name):
#     try:
#         gdb_data = gpd.read_file(gdb_path, layer = layer_name)
#         # print("\nGeoDataFrame 的信息概览：")
#         # gdb_data.info()
#         return gdb_data
#
#     except Exception as e:
#         print(f"\n读取 GDB 数据时发生错误: {e}")
#         print("请检查以下几点：")
#         print(f"1. GDB 路径 '{gdb_path}' 和要素类名称 '{layer_name}' 是否正确。")
#         print("2. 你的 Python 环境是否已成功安装 geopandas、fiona 和 pyogrio。")
#         print("3. GDB 文件是否被其他程序（如 ArcGIS Pro/ArcMap）锁定。")

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    root = tk.Tk()
    app = FileProcessingApp(root)
    root.mainloop()

    # #读取已有数据2024
    # #读取新数据
    # path = "D:\智能电子地图项目\归档\LRDLclip01\LRDL.gdb"
    # #读取数据时的相应的层名 layer_name1--L7-10;2--L11-L12;3--L13-L14；4--L15-L17;layer_name是待处理数据数据
    # layer_name1 = "layer1"
    # layer_name2 = "layer2"
    # layer_name3 = "layer3"
    # layer_name4 = "layer4"
    # layer_name = "LRDL_3"
    # #layer_name为需要读取的数据层
    # #1--L7-L10
    # layer1 = read_file(path,layer_name1)
    # #2--L11-L12
    # layer2 = read_file(path, layer_name2)
    # #3--L13-L14
    # layer3 = read_file(path, layer_name3)
    # # 4--L15-L17
    # layer4 = read_file(path, layer_name4)
    # #读取待处理的新数据
    # layer_read = read_file(path, layer_name)
    # #拷贝数据
    # layer_new = layer_read.copy()
    #
    #
    #
    # #为保证后续cover的使用，将数据都转换成投影坐标的
    # target_crs = "EPSG:4540"
    # #数据做投影
    # layer_new_proj = layer_new.to_crs(target_crs)
    # layer1_proj = layer1.to_crs(target_crs)
    # layer2_proj = layer2.to_crs(target_crs)
    # layer3_proj = layer3.to_crs(target_crs)
    # layer4_proj = layer4.to_crs(target_crs)
    #
    # # print(layer_new_proj.geometry)
    # # print(layer1.geometry)
    #
    #
    #
    # #为数据添加字段;assign会返回一个新的GeoDataFrame，不是修改原来的
    # print("\n--- 使用 .assign() 添加字段 ---")
    # lrdl_backup = layer_new_proj.assign(
    #     L7 = 2,
    #     L8 = 2,
    #     L9 = 2,
    #     L10 = 2,
    #     code2_1 = "",
    #     symbol2_1 = "",
    #     L11 = 2,
    #     L12 = 2,
    #     L13 = 2,
    #     L14 = 2,
    #     code2_2 = "",
    #     symbol2_2 = "",
    #     L15 = 2,
    #     L16 = 2,
    #     L17 = 2,
    #     code2_3 = "",
    #     symbol2_3 = "",
    #     BZ = ""
    #
    # )
    # #将assign添加的列按照规定的顺序出现
    # existing_cols = layer_new_proj.columns.tolist()
    # new_cols_in_order = ['L7', 'L8', 'L9', 'L10', 'code2_1', 'symbol2_1', 'L11', 'L12', 'L13', 'L14', 'code2_2', 'symbol2_2', 'L15', 'L16', 'L17', 'code2_3', 'symbol2_3', 'BZ']
    # #构建最终的列顺序
    # final_column_order = existing_cols + new_cols_in_order
    # #按顺序拍好新加入列的df数据,lrdl_backup是投影坐标数据==lrdl_final是投影坐标数据
    # lrdl_final = lrdl_backup[final_column_order]
    # #查找是否有相应需要的字段
    # print(f"DEBUG: Columns before error: {lrdl_final.columns}")
    #
    #
    #
    # #进入具体实现covers环节
    # #先做缓冲区，保证可以选上
    # #第1级distance
    # buffer_distance1 = 100
    # #第2级distance
    # buffer_distance2 = 15
    # #第3级的distance
    # buffer_distance3 = 2  # 示例：，请根据实际地图单位调整
    #
    # #对L7-L10处理
    # data_level1.data_level_1(layer1_proj, lrdl_final, buffer_distance1)
    # # 对11-12层进行处理
    # data_level2.data_level_2(layer2_proj, lrdl_final, buffer_distance2)
    # #对13-14层进行处理
    # data_level2.data_level_3(layer3_proj, lrdl_final, buffer_distance2)
    # #对L15-L17层数据进行处理
    # data_level3.data_level_4(layer4_proj, lrdl_final,buffer_distance3)
    #
    #
    # #输出
    # print("结果")
    # print(lrdl_final[['L7', 'L8', 'L9', 'L10','L11','L12','L13','L14','L15','L16','L17']].head(15))
    # try:
    #     lrdl_final.to_file("D:\智能电子地图项目\data_r2.shp", encoding='utf-8')
    #     print(f"数据已成功输出，使用 UTF-8 编码。")
    #     print("请注意检查：")
    #     print("  - Shapefile 包含: .shp, .shx, .dbf, .prj 等多个文件。")
    #     print("  - 列名 'name' 可能被截断为 '名称'。")
    #     print("  - 列名 'value_long_name' 可能被截断为 '长值'。")
    #     print(
    #         "  - 如果原始 GeoDataFrame 包含混合几何类型，输出的 Shapefile 只会包含其中一种类型（通常是第一行遇到的类型），其他类型的数据可能被忽略。建议按几何类型分别输出。")
    # except Exception as e:
    #     print(f"输出 Shapefile 时发生错误: {e}")














