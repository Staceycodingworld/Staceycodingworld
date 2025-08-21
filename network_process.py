from itertools import combinations
import geopandas as gpd
import networkx as nx
from shapely.geometry import Point, LineString
import matplotlib.pyplot as plt
import pandas as pd

# 全局变量
tolerance_high = 3
tolerance_mid = 4
tolerance_low = 6


def build_graph_from_gdf(gdf):
    # 检查是否存在 'MultiLineString'
    has_multilinestring = (gdf.geom_type == 'MultiLineString').any()
    if has_multilinestring:
        gdf = gdf.explode(index_parts=False)  # index_parts=False 避免创建多级索引
    else:
        print("不存在MultiString")
    # 对于路网，通常使用有向图 (DiGraph)，因为道路可能是单向的
    g = nx.DiGraph()

    # --- 2. 遍历 GeoDataFrame 并添加节点和边 ---
    # 字典用于存储已添加的节点，键是 Shapely Point 对象的哈希值或字符串表示，值是 NetworkX 节点ID
    # 这有助于避免重复添加节点，并处理线段的共享端点
    node_mapping = {}
    node_counter = 0

    print("\n正在将 GeoDataFrame 转换为 NetworkX 图...")

    for index, row in gdf.iterrows():
        geometry = row['geometry']  # 获取 LineString 几何对象

        if geometry is None or not isinstance(geometry, LineString):
            # 跳过无效的几何数据
            # print(f"跳过无效几何类型或空几何数据在索引: {index}")
            continue

        # 获取线段的起点和终点
        start_point = geometry.coords[0]
        end_point = geometry.coords[-1]
        # 将坐标转换为 Shapely Point 对象，便于哈希和比较
        # 或者直接使用坐标元组作为键
        # 对于浮点数比较，直接使用元组键可能会有精度问题，但对于常见的地理数据通常够用
        start_key = tuple(start_point)
        end_key = tuple(end_point)
        # 检查起点是否已存在于节点映射中，如果不存在则添加新节点---可舍去NetworkX帮忙处理了这个问题
        if start_key not in node_mapping:
            node_mapping[start_key] = node_counter
            g.add_node(node_counter, pos=start_point, geometry=Point(start_point))
            node_counter += 1
        u = node_mapping[start_key]

        # 检查终点是否已存在于节点映射中，如果不存在则添加新节点
        if end_key not in node_mapping:
            node_mapping[end_key] = node_counter
            g.add_node(node_counter, pos=end_point, geometry=Point(end_point))
            node_counter += 1
        v = node_mapping[end_key]

        # 将 Shapefile 的属性添加到 NetworkX 边的属性中
        # 排除 'geometry' 列本身，因为那是线段对象
        edge_attributes = {col: row[col] for col in gdf.columns if col != 'geometry'}
        edge_attributes['geometry'] = geometry  # 将原始几何对象也作为边属性存储
        edge_attributes['road_id'] = index   # 增加一个road_id
        # 对于双向道路，可能需要额外逻辑：
        # 如果你的SHP数据中一条线代表一个双向道路，你需要添加两条边 (u->v 和 v->u)
        # 否则，如果每条记录本身就代表一个方向，则只添加一条边
        # 这里我们默认添加一条从起点到终点的边
        if row['SDTF'] == '单':
            g.add_edge(u, v, **edge_attributes)
        else:
            g.add_edge(u, v, **edge_attributes)
            g.add_edge(v, u, **edge_attributes)

    print("NetworkX 图构建完成！")
    # identify disconnected components
    components = list(nx.weakly_connected_components(g))
    return g, components


# 得到弱连通分量的gdf以及其中节点的几何信息
def get_components_geometry(components, g):
    all_component_geometries = []  # 用于存储所有连通分量的几何数据.一个列表存储一系列的gdf
    for i, component_nodes in enumerate(components):
        print(f"\n--- 连通分量 {i + 1} (包含 {len(component_nodes)} 个节点) ---")
        # 存储当前连通分量中节点的几何信息
        current_component_geometries = []
        current_component_data = []  # 用于创建 GeoDataFrame，这里创建的是列表
        for node_id in component_nodes:
            # # g.edges(node)返回一个生成器，list将他转换为列表
            # edge_data = list(g.edges(node_id, data=True))[0]
            # # 提取这条边的两个节点和其数据
            # u, v, data = edge_data
            # # 从边属性中获取道路ID
            # road_id = data['road_id']
            # 从图g中获取该点的属性字典
            node_attribute = g.nodes[node_id]
            geometry = node_attribute.get('geometry')
            if geometry:
                # 将节点数据添加到当前分量的列表中
                current_component_geometries.append(geometry)
                # comp_id分量id
                current_component_data.append({'comp_id': i, 'node_id': node_id, 'geometry': geometry})
            else:
                print("未找到几何信息")
        # 将当前所有连通分量的节点打包成gdf
        if current_component_data:
            # 将当前节点数据添加到总列表--转成投影坐标系--crs是必要的
            comp_gdf = gpd.GeoDataFrame(current_component_data, crs="EPSG:4540")
            # 存储每个连通分量的节点geodataframe--这里是一个列表
            all_component_geometries.append(comp_gdf)
    return all_component_geometries


def get_processed_roads(g):
    isolated_roads = []
    dangling_roads = []
    # 使用集合来跟踪已处理的道路ID，避免重复
    processed_road_ids = set()

    # 遍历图中的所有边，而不是节点。这样可以确保每条道路只处理一次
    for u, v, data in g.edges(data=True):
        road_id = data.get('road_id')
        if not road_id or road_id in processed_road_ids:
            continue

        # 获取道路两端的节点
        node1 = u
        node2 = v

        # 获取两个节点的总度
        total_degree1 = g.in_degree(node1) + g.out_degree(node1)
        total_degree2 = g.in_degree(node2) + g.out_degree(node2)

        # 检查是否为双向道路（即存在相反方向的边）
        is_bidirectional = g.has_edge(node2, node1)

        # 悬挂路段逻辑
        # 只要有一端的度是1或2（取决于是否双向）且另一端度更大，就是悬挂路
        if (total_degree1 == 1 and total_degree2 > 1) or \
                (total_degree2 == 1 and total_degree1 > 1) or \
                (is_bidirectional and total_degree1 == 2 and total_degree2 > 2) or \
                (is_bidirectional and total_degree2 == 2 and total_degree1 > 2):

            # 找到悬挂端的节点（度较小的那端）
            if total_degree1 < total_degree2:
                hanging_node = node1
            else:
                hanging_node = node2

            hanging_node_geometry = g.nodes[hanging_node].get('geometry')
            dangling_roads.append({
                'road_id': road_id,
                'geometry': hanging_node_geometry,
                'is_bidirectional': is_bidirectional
            })
            processed_road_ids.add(road_id)

        # 孤立路段逻辑
        # 两端节点的度相等且很小，则为孤立路段
        elif total_degree1 == total_degree2:
            if total_degree1 == 1:
                # 单向孤立路段
                isolated_roads.append(road_id)
                processed_road_ids.add(road_id)
            elif total_degree1 == 2 and is_bidirectional:
                # 双向孤立路段
                isolated_roads.append(road_id)
                processed_road_ids.add(road_id)

    # 检查列表是否为空，并创建GeoDataFrame
    if dangling_roads:
        dangling_roads_gdf = gpd.GeoDataFrame(
            dangling_roads,
            geometry='geometry',
            crs="EPSG:4540"
        )
    else:
        dangling_roads_gdf = gpd.GeoDataFrame({
            'road_id': [],
            'geometry': [],
            'is_bidirectional': []
        }, geometry='geometry', crs="EPSG:4540")

    return isolated_roads, dangling_roads_gdf
    # isolated_roads = []
    # # 创建两个空列表来存储悬挂路相关的数据
    # dangling_roads = []
    # # 使用集合来跟踪已处理的边，以避免重复处理
    # processed_edges = set()
    # # 遍历图中的所有节点及其度
    # for node in g.nodes():
    #     # 获取节点的总度
    #     total_degree = g.in_degree(node) + g.out_degree(node)
    #     # 逻辑1 处理单向道路情况
    #     if total_degree == 1:
    #         # 找到和这个节点相连的边
    #         # g.edges(node,data=True)会同时返回出边和入边
    #         edge_data = list(g.edges(node, data=True))[0]
    #
    #         # 提取这条边的两个节点和其数据
    #         u, v, data = edge_data
    #         # 使用元组来表示边，并进行排序保证唯一性
    #         # 即这样 u->v 和 v->u，都能被视为同一条
    #         edge_tuple = tuple(sorted((u, v)))
    #
    #         # 如果这条边已经被处理过则跳过
    #         if edge_tuple in processed_edges:
    #             continue
    #
    #         # 检查与这条边相连的另一个结点的总度
    #         other_node = v if u == node else u
    #         other_node_degree = g.in_degree(other_node) + g.out_degree(other_node)
    #
    #         if other_node_degree > 1:
    #             # 悬挂路段（一端总度为一，另一端总度大于1）
    #             road_id = data['road_id']
    #             hangling_node_geometry = g.nodes[node]['geometry']
    #             dangling_roads.append({
    #                 'road_id': road_id,
    #                 'geometry': hangling_node_geometry
    #
    #             })
    #         elif other_node_degree == 1:
    #             # 孤立路段（两端总度都为1）
    #             road_id = data['road_id']
    #             isolated_roads.append(road_id)
    #         processed_edges.add(edge_tuple)
    #
    #     # 逻辑2 主要处理的是双向道路的情况
    #     elif total_degree == 2:
    #         # 检查入度是否为1，出度是否为1
    #         if g.in_degree(node) == 1 and g.out_degree(node) == 1:
    #             # 获取其唯一邻居
    #             # 这里我们假设一个有向边 (u, v)，v的唯一出度邻居是v。但我们需要的是u。
    #             # NetworkX提供了predecessors和successors
    #             # 寻找这个节点的唯一前驱（predecessor）
    #             predecessor = list(g.predecessors(node))[0]
    #             # 检查前驱节点的总度是否也为2
    #             predecessor_degree = g.in_degree(predecessor) + g.out_degree(predecessor)
    #
    #             if predecessor_degree > 2:
    #                 # g.edges(node,data=True)会同时返回出边和入边
    #                 edge_data = list(g.edges(node, data=True))[0]
    #                 # 提取这条边的两个节点和其数据
    #                 u, v, data = edge_data
    #                 edge_tuple = tuple(sorted((node, predecessor)))
    #                 if edge_tuple in processed_edges:
    #                     continue
    #                 hangling_node_geometry = g.nodes[node]['geometry']
    #                 dangling_roads.append({
    #                     'road_id': data['road_id'],
    #                     'geometry': hangling_node_geometry,
    #                     'is_bidirectional': True
    #                 })
    #                 processed_edges.add(edge_tuple)
    #             elif predecessor_degree == 2:
    #                 # g.edges(node,data=True)会同时返回出边和入边
    #                 edge_data = list(g.edges(node, data=True))[0]
    #                 # 提取这条边的两个节点和其数据
    #                 u, v, data = edge_data
    #                 # 找到了双向的孤立路段
    #                 # 避免重复，只需处理一次
    #                 edge_tuple = tuple(sorted((node, predecessor)))
    #                 if edge_tuple in processed_edges:
    #                     continue
    #
    #                 isolated_roads.append(data['road_id'])
    #
    #                 processed_edges.add(edge_tuple)
    #
    # # 检查列表是否为空，并创建GeoDataFrame
    # if dangling_roads:
    #     dangling_roads_gdf = gpd.GeoDataFrame(
    #         dangling_roads,
    #         geometry='geometry',
    #         crs="EPSG:4540"
    #     )
    # else:
    #     # 列表为空时，创建一个空的gdf，以保持函数返回类型一致
    #     dangling_roads_gdf = gpd.GeoDataFrame({
    #         'road_id': [],
    #         'geometry': []
    #     }, geometry='geometry', crs="EPSG:4540")
    # return isolated_roads, dangling_roads_gdf
    #     if g.degree(node) == 1:
    #         # 检查结点的度是否为1，1是一个没有连接的端点
    #         # 找出和这个节点相连的边
    #         # g.edges(node)返回一个生成器，list将他转换为列表
    #         edge_data = list(g.edges(node, data=True))[0]
    #         # 提取这条边的两个节点和其数据
    #         u, v, data = edge_data
    #         # 检查与这条边相连的另一个结点的度
    #         other_node = v if u == node else u
    #
    #         if g.degree(other_node) > 1:
    #             # 从边属性中获取道路ID和几何信息
    #             road_id = data['road_id']
    #             # 从节点属性中获取断裂点的坐标
    #             hanging_node_geometry = g.nodes[node]['geometry']
    #             # 获取道路id以及断裂点的坐标用于后续匹配
    #             dangling_roads.append({
    #                 'road_id': road_id,
    #                 'geometry': hanging_node_geometry
    #             })
    #         if g.degree(other_node) == 1:
    #             # 从边属性中获取道路ID和几何信息
    #             road_id = data['road_id']
    #             if road_id not in isolated_roads:
    #                 isolated_roads.append(road_id)
    #
    # # 检查列表是否为空
    # if dangling_roads:
    #     # 列表非空，直接用它创建 GeoDataFrame
    #     dangling_roads_gdf = gpd.GeoDataFrame(
    #         dangling_roads,
    #         geometry='geometry',
    #         crs="EPSG:4540"
    #     )
    # else:
    #     columns_to_include = ['road_id']
    #     empty_df = pd.DataFrame(columns=columns_to_include)
    #     empty_geometry = gpd.GeoSeries(dtype='object', crs="EPSG:4540")
    #     # 列表为空，创建一个空的但包含正确列和CRS的GeoDataFrame
    #     dangling_roads_gdf = gpd.GeoDataFrame(empty_df, geometry=empty_geometry, crs="EPSG:4540")



# 处理数据的核心部分
def process_core(component_gdfs, gdf_pro, tolerance):
    # 传入节点信息的gdf--包含comp_id和geometry
    # 计算不同弱连通分量之间的最短空间距离
    closest_point_pairs_list = []
    pair_counter = 0
    for comp1_gdf, comp2_gdf in combinations(component_gdfs, 2):
        comp2_gdf_new = comp2_gdf.copy()
        # comp2_gdf_new.set_geometry('geometry_right', inplace=True)
        comp2_gdf_new['geometry_right'] = comp2_gdf_new['geometry']
        nearest_join_result = comp1_gdf.sjoin_nearest(comp2_gdf_new, how="inner", distance_col="spatial_dist")
        if not nearest_join_result.empty:  # 这一步才是从点对中筛选最近的
            min_dist_row = nearest_join_result.loc[nearest_join_result['spatial_dist'].idxmin()]
            min_distance = min_dist_row['spatial_dist']
            closest_point_pairs_list.append({
                'pair_id': pair_counter,
                'distance': min_distance,
                'geometry': min_dist_row.geometry,
            })
            closest_point_pairs_list.append({
                'pair_id': pair_counter,
                'distance': min_distance,
                'geometry': min_dist_row['geometry_right'],
            })
            pair_counter += 1
    closest_point_pairs_gdf = gpd.GeoDataFrame(closest_point_pairs_list, crs="EPSG:4540")
    print("\n找到的弱连通分量之间的最近点对:")
    print(closest_point_pairs_gdf)
    print(closest_point_pairs_gdf[['pair_id', 'distance', 'geometry']].to_string())

    # 提取所有低等级道路的端点，并加入长度信息
    low_grade_endpoints = []
    has_multilinestring = (gdf_pro.geom_type == 'MultiLineString').any()
    if has_multilinestring:
        gdf_pro = gdf_pro.explode(index_parts=False)  # index_parts=False 避免创建多级索引
    else:
        print("不存在MultiString")
    for road_index, row in gdf_pro.iterrows():
        low_grade_endpoints.append({
            'road_id': road_index,
            'endpoint_type': 'start',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[0])
        })
        low_grade_endpoints.append({
            'road_id': road_index,
            'endpoint_type': 'end',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[-1])
        })

    low_grade_endpoints_gdf = gpd.GeoDataFrame(low_grade_endpoints, crs="EPSG:4540")
    low_grade_endpoints_gdf.set_geometry('geometry')
    # 使用 sjoin_nearest 一次性找到每个低等级道路端点最近的最近点对端点
    # distance_col='match_distance' 存储低等级道路端点与最近点对端点的距离
    match_result = gpd.sjoin_nearest(
        low_grade_endpoints_gdf,
        closest_point_pairs_gdf,   # 这里把closest的点对改为点对进行测试
        how='inner',
        distance_col='match_distance'
    )
    #  筛选出距离非常小的点，认为他们是连接点
    #  并确保每条道路端点只匹配了一个最近点对端点
    match_result = match_result.loc[match_result['match_distance'] < tolerance]
    match_result = match_result.loc[match_result.groupby(['road_id', 'endpoint_type'])['match_distance'].idxmin()]
    #  将结果合并，以便我们知道每条低等级道路的起点和终点匹配了哪个最近点对
    low_road_matches = match_result.pivot_table(
        index='road_id',
        columns='endpoint_type',
        values=['pair_id', 'geometry_length'],
        aggfunc='first'  # 指定聚合函数为 'first'
    )
    low_road_matches.columns = [f'{col[0]}_{col[1]}' for col in low_road_matches.columns]
    # 检查并添加缺失的列
    if 'pair_id_start' not in low_road_matches.columns:
        low_road_matches['pair_id_start'] = None
    if 'pair_id_end' not in low_road_matches.columns:
        low_road_matches['pair_id_end'] = None
    if 'geometry_length_start' not in low_road_matches.columns:
        low_road_matches['geometry_length_start'] = None
    if 'geometry_length_end' not in low_road_matches.columns:
        low_road_matches['geometry_length_end'] = None
    low_road_matches = low_road_matches.reset_index()
    # # 检查并添加缺失的列
    # required_cols = ['pair_id_start', 'pair_id_end', 'geometry_length_start', 'geometry_length_end',
    #                  'road_id_right_start', 'road_id_right_end']
    # for col in required_cols:
    #     if col not in low_road_matches.columns:
    #         low_road_matches[col] = None

    print(low_road_matches)
    #  筛选出起点和终点匹配了同一最近点对id的道路
    connecting_roads_df = low_road_matches[
        low_road_matches['pair_id_start'] == low_road_matches['pair_id_end']
        ]
    connecting_roads_df = connecting_roads_df.dropna()
    return connecting_roads_df, low_grade_endpoints_gdf


def process_assist(component_gdfs, gdf_pro, tolerance):
    # 提取每个弱连通分量的所有节点
    nodes_gdf = pd.concat(component_gdfs, ignore_index=True)
    # 另一种逻辑
    # 提取所有低等级道路的端点，并加入长度信息
    low_grade_endpoints = []
    has_multilinestring = (gdf_pro.geom_type == 'MultiLineString').any()
    if has_multilinestring:
        gdf_pro = gdf_pro.explode(index_parts=False)  # index_parts=False 避免创建多级索引
    else:
        print("不存在MultiString")
    for road_index, row in gdf_pro.iterrows():
        low_grade_endpoints.append({
            'road_id': road_index,
            'endpoint_type': 'start',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[0])
        })
        low_grade_endpoints.append({
            'road_id': road_index,
            'endpoint_type': 'end',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[-1])
        })

    low_grade_endpoints_gdf = gpd.GeoDataFrame(low_grade_endpoints, crs="EPSG:4540")
    low_grade_endpoints_gdf.set_geometry('geometry')
    # 使用sjoin——nearest进行端点-节点匹配
    # 设置一合适的max_distance
    max_distance = tolerance
    matched_endpoints = gpd.sjoin_nearest(
        low_grade_endpoints_gdf,
        nodes_gdf,
        how='inner',
        max_distance=max_distance,
        distance_col='distance_to_node'  # 端点匹配节点时差的距离

    )
    # 对matched_endpoints按road_id分组
    # 并获取到每条道路匹配到的所有不重复组件ID
    road_component_matches = matched_endpoints.groupby('road_id')['comp_id'].agg(
        lambda x: list(set(x))
    ).reset_index()

    # road_component_matches = matched_endpoints.groupby('road_id_left')['comp_id'].agg(
    #     lambda x: list(set(x))
    # ).reset_index()
    # 筛选出连接了两个或更多不同组件的道路
    # 如果一个道路的两个端点分别连接到了不同的组件，那么com_id的集合长度会大于1
    cross_component_bridge_ids = road_component_matches[
        road_component_matches['comp_id'].apply(len) > 1
        ]['road_id'].tolist()
    print("筛选出连接两个或更多不同组件的道路：")
    # cross_component_bridge_ids是一个包含了2列的gdf
    print(cross_component_bridge_ids)
    # cross_component_bridge_ids = cross_component_bridge_ids[cross_component_bridge_ids['']]
    return cross_component_bridge_ids


# L7的处理逻辑
# 传入的gdfs，是一系列gdf组成的列表
# 处理的gdf应该是L8_L17
def process_l7(component_gdfs, gdf, g):
    # 选取比L7等级低的数据处理--测试已结束换回原逻辑等级--再测
    gdf_pro = gdf[gdf['L7'] != '1']
    # 处理的核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_high)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'L7'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            row = gdf.loc[index_value]
            if row['L8'] != '1':
                gdf.loc[index_value, 'L8'] = '3'
            if row['L9'] != '1':
                gdf.loc[index_value, 'L9'] = '3'
            if row['L10'] != '1':
                gdf.loc[index_value, 'L10'] = '3'
            if row['L11'] != '1':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_high)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'L7'] = '3'
                # 把备注改了先
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                row = gdf.loc[index_value]
                if row['L8'] != '1':
                    gdf.loc[index_value, 'L8'] = '3'
                if row['L9'] != '1':
                    gdf.loc[index_value, 'L9'] = '3'
                if row['L10'] != '1':
                    gdf.loc[index_value, 'L10'] = '3'
                if row['L11'] != '1':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l7无需要通过弱连通分量处理的数据！")
    # ！！！！！对L7的一些相关的处理
    print("L7开始通过悬挂路逻辑处理：")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    for index_value in isolated_roads:
        # L11级往上不处理这个情况
        # isolated_roads是存储索引的列表，row通过.loc方法从gdf中获取到原gdf中的相应行
        row = gdf.loc[index_value]
        # 获取当前道路的节点
        road_endpoints = [{
            'road_id': index_value,
            'endpoint_type': 'start',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[0])
        }, {
            'road_id': index_value,
            'endpoint_type': 'end',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[-1])
        }]
        road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
        # 寻找匹配节点及其对应的road_id
        matched_gdf = gpd.sjoin_nearest(
            left_df=low_grade_endpoints_gdf,
            right_df=road_endpoints_gdf,
            how='inner',
            max_distance=tolerance_mid,
        )
        if not matched_gdf.empty:
            # 直接处理和我们当前孤立路段连接的
            for road_index in matched_gdf.index:
                index_value = matched_gdf.loc[road_index]['road_id_left']
                gdf.loc[index_value, 'L7'] = '3'
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                row = gdf.loc[index_value]
                if row['L8'] != '1':
                    gdf.loc[index_value, 'L8'] = '3'
                if row['L9'] != '1':
                    gdf.loc[index_value, 'L9'] = '3'
                if row['L10'] != '1':
                    gdf.loc[index_value, 'L10'] = '3'
                if row['L11'] != '1':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1':
                    gdf.loc[index_value, 'L17'] = '3'
    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("L7悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L7'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            row = gdf.loc[index_value]
            if row['L8'] != '1':
                gdf.loc[index_value, 'L8'] = '3'
            if row['L9'] != '1':
                gdf.loc[index_value, 'L9'] = '3'
            if row['L10'] != '1':
                gdf.loc[index_value, 'L10'] = '3'
            if row['L11'] != '1':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1':
                gdf.loc[index_value, 'L17'] = '3'
    return gdf


def process_l8(component_gdfs, gdf, g):
    gdf_pro = gdf[(gdf['L8'] != '1') & (gdf['L8'] != '3')]
    # 处理核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_high)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'L8'] = '3'
            gdf.loc[index_value, 'code2_1'] = '42090120'
            gdf.loc[index_value, 'symbol2_1'] = '高速公路'
            row = gdf.loc[index_value]
            if row['L9'] != '1' and row['L9'] != '3':
                gdf.loc[index_value, 'L9'] = '3'
            if row['L10'] != '1' and row['L10'] != '3':
                gdf.loc[index_value, 'L10'] = '3'
            if row['L11'] != '1' and row['L11'] != '3':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_high)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'L8'] = '3'
                gdf.loc[index_value, 'code2_1'] = '42090120'
                gdf.loc[index_value, 'symbol2_1'] = '高速公路'
                row = gdf.loc[index_value]
                if row['L9'] != '1' and row['L9'] != '3':
                    gdf.loc[index_value, 'L9'] = '3'
                if row['L10'] != '1' and row['L10'] != '3':
                    gdf.loc[index_value, 'L10'] = '3'
                if row['L11'] != '1' and row['L11'] != '3':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l8没有需要通过弱连通分量处理的数据")
    print("L8开始通过悬挂路逻辑处理：")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    for index_value in isolated_roads:
        # L11级往上不处理这个情况
        # isolated_roads是存储索引的列表，row通过.loc方法从gdf中获取到原gdf中的相应行
        row = gdf.loc[index_value]
        # 获取当前道路的节点
        road_endpoints = [{
            'road_id': index_value,
            'endpoint_type': 'start',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[0])
        }, {
            'road_id': index_value,
            'endpoint_type': 'end',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[-1])
        }]
        road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
        # 寻找匹配节点及其对应的road_id
        matched_gdf = gpd.sjoin_nearest(
            left_df=low_grade_endpoints_gdf,
            right_df=road_endpoints_gdf,
            how='inner',
            max_distance=tolerance_mid,
        )
        if not matched_gdf.empty:
            # 直接处理和我们当前孤立路段连接的
            for road_index in matched_gdf.index:
                index_value = matched_gdf.loc[road_index]['road_id_left']
                gdf.loc[index_value, 'L8'] = '3'
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'code2_1'] = '42090120'
                gdf.loc[index_value, 'symbol2_1'] = '高速公路'
                row = gdf.loc[index_value]
                if row['L9'] != '1' and row['L9'] != '3':
                    gdf.loc[index_value, 'L9'] = '3'
                if row['L10'] != '1' and row['L10'] != '3':
                    gdf.loc[index_value, 'L10'] = '3'
                if row['L11'] != '1' and row['L11'] != '3':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("L8悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L8'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'code2_1'] = '42090120'
            gdf.loc[index_value, 'symbol2_1'] = '高速公路'
            row = gdf.loc[index_value]
            if row['L9'] != '1' and row['L9'] != '3':
                gdf.loc[index_value, 'L9'] = '3'
            if row['L10'] != '1' and row['L10'] != '3':
                gdf.loc[index_value, 'L10'] = '3'
            if row['L11'] != '1' and row['L11'] != '3':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    return gdf


# 处理L9的数据
def process_l9(component_gdfs, gdf, g):
    # 找到低于L9级的道路
    gdf_pro = gdf[(gdf['L9'] != '1') & (gdf['L9'] != '3')]
    # 处理核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_high)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'L9'] = '3'
            gdf.loc[index_value, 'code2_1'] = '42010120'
            gdf.loc[index_value, 'symbol2_1'] = '国道'
            row = gdf.loc[index_value]
            if row['L10'] != '1' and row['L10'] != '3':
                gdf.loc[index_value, 'L10'] = '3'
            if row['L11'] != '1' and row['L11'] != '3':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_high)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'L9'] = '3'
                gdf.loc[index_value, 'code2_1'] = '42010120'
                gdf.loc[index_value, 'symbol2_1'] = '国道'
                row = gdf.loc[index_value]
                if row['L10'] != '1' and row['L10'] != '3':
                    gdf.loc[index_value, 'L10'] = '3'
                if row['L11'] != '1' and row['L11'] != '3':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l9没有需要通过弱连通分量处理的数据")
    print("L9开始通过悬挂路逻辑处理：")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    for index_value in isolated_roads:
        # L11级往上不处理这个情况--悬挂路隐藏
        # isolated_roads是存储索引的列表，row通过.loc方法从gdf中获取到原gdf中的相应行
        row = gdf.loc[index_value]
        # 获取当前道路的节点
        road_endpoints = [{
            'road_id': index_value,
            'endpoint_type': 'start',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[0])
        }, {
            'road_id': index_value,
            'endpoint_type': 'end',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[-1])
        }]
        road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
        # 寻找匹配节点及其对应的road_id
        matched_gdf = gpd.sjoin_nearest(
            left_df=low_grade_endpoints_gdf,
            right_df=road_endpoints_gdf,
            how='inner',
            max_distance=tolerance_mid,
        )
        if not matched_gdf.empty:
            # 直接处理和我们当前孤立路段连接的
            for road_index in matched_gdf.index:
                index_value = matched_gdf.loc[road_index]['road_id_left']
                gdf.loc[index_value, 'L9'] = '3'
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'code2_1'] = '42010120'
                gdf.loc[index_value, 'symbol2_1'] = '国道'
                row = gdf.loc[index_value]
                if row['L10'] != '1' and row['L10'] != '3':
                    gdf.loc[index_value, 'L10'] = '3'
                if row['L11'] != '1' and row['L11'] != '3':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("L9悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L9'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'code2_1'] = '42010120'
            gdf.loc[index_value, 'symbol2_1'] = '国道'
            row = gdf.loc[index_value]
            if row['L10'] != '1' and row['L10'] != '3':
                gdf.loc[index_value, 'L10'] = '3'
            if row['L11'] != '1' and row['L11'] != '3':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    return gdf


# L10处理
def process_l10(component_gdfs, gdf, g):
    # 找到低于L10级的道路
    gdf_pro = gdf[(gdf['L10'] != '1') & (gdf['L10'] != '3')]
    # 处理核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_high)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'L10'] = '3'
            gdf.loc[index_value, 'code2_1'] = '42020120'
            gdf.loc[index_value, 'symbol2_1'] = '省道'
            row = gdf.loc[index_value]
            if row['L11'] != '1' and row['L11'] != '3':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_high)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'L10'] = '3'
                gdf.loc[index_value, 'code2_1'] = '42020120'
                gdf.loc[index_value, 'symbol2_1'] = '省道'
                row = gdf.loc[index_value]
                if row['L11'] != '1' and row['L11'] != '3':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l10没有需要通过弱连通分量处理显示层级的道路")
    print("L10开始通过悬挂路逻辑处理：")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    for index_value in isolated_roads:
        # L11级往上不处理这个情况--悬挂路隐藏
        # isolated_roads是存储索引的列表，row通过.loc方法从gdf中获取到原gdf中的相应行
        row = gdf.loc[index_value]
        # 获取当前道路的节点
        road_endpoints = [{
            'road_id': index_value,
            'endpoint_type': 'start',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[0])
        }, {
            'road_id': index_value,
            'endpoint_type': 'end',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[-1])
        }]
        road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
        # 寻找匹配节点及其对应的road_id
        matched_gdf = gpd.sjoin_nearest(
            left_df=low_grade_endpoints_gdf,
            right_df=road_endpoints_gdf,
            how='inner',
            max_distance=tolerance_mid,
        )
        if not matched_gdf.empty:
            # 直接处理和我们当前孤立路段连接的
            for road_index in matched_gdf.index:
                index_value = matched_gdf.loc[road_index]['road_id_left']
                gdf.loc[index_value, 'L10'] = '3'
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'code2_1'] = '42020120'
                gdf.loc[index_value, 'symbol2_1'] = '省道'
                row = gdf.loc[index_value]
                if row['L11'] != '1' and row['L11'] != '3':
                    gdf.loc[index_value, 'L11'] = '3'
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("L10悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L10'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'code2_1'] = '42020120'
            gdf.loc[index_value, 'symbol2_1'] = '省道'
            row = gdf.loc[index_value]
            if row['L11'] != '1' and row['L11'] != '3':
                gdf.loc[index_value, 'L11'] = '3'
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    return gdf


# L11处理
def process_l11(component_gdfs, gdf, g):
    gdf_pro = gdf[(gdf['L11'] != '1') & (gdf['L11'] != '3')]
    # 处理核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_mid)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'L11'] = '3'
            gdf.loc[index_value, 'code2_2'] = '42020120'
            gdf.loc[index_value, 'symbol2_2'] = '省道'
            row = gdf.loc[index_value]
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_mid)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'L11'] = '3'
                gdf.loc[index_value, 'code2_2'] = '42020120'
                gdf.loc[index_value, 'symbol2_2'] = '省道'
                row = gdf.loc[index_value]
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l11没有需要通过弱连通分量处理显示层级的数据")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    print("L11开始通过悬挂路逻辑处理")
    for index_value in isolated_roads:
        # L11级往上不处理这个情况
        # isolated_roads是存储索引的列表，row通过.loc方法从gdf中获取到原gdf中的相应行
        row = gdf.loc[index_value]
        # 获取当前道路的节点
        road_endpoints = [{
            'road_id': index_value,
            'endpoint_type': 'start',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[0])
        }, {
            'road_id': index_value,
            'endpoint_type': 'end',
            'geometry_length': row['geometry'].length,
            'geometry': Point(row['geometry'].coords[-1])
        }]
        road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
        # 寻找匹配节点及其对应的road_id
        matched_gdf = gpd.sjoin_nearest(
            left_df=low_grade_endpoints_gdf,
            right_df=road_endpoints_gdf,
            how='inner',
            max_distance=tolerance_mid,
        )
        if not matched_gdf.empty:
            # 直接处理和我们当前悬挂路点连接的
            for road_index in matched_gdf.index:
                index_value = matched_gdf.loc[road_index]['road_id_left']
                gdf.loc[index_value, 'L11'] = '3'
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'code2_2'] = '42020120'
                gdf.loc[index_value, 'symbol2_2'] = '省道'
                row = gdf.loc[index_value]
                if row['L12'] != '1' and row['L12'] != '3':
                    gdf.loc[index_value, 'L12'] = '3'
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("L11悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L11'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'code2_2'] = '42020120'
            gdf.loc[index_value, 'symbol2_2'] = '省道'
            row = gdf.loc[index_value]
            if row['L12'] != '1' and row['L12'] != '3':
                gdf.loc[index_value, 'L12'] = '3'
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    return gdf


# L12处理
def process_l12(component_gdfs, gdf, g):
    gdf_pro = gdf[(gdf['L12'] != '1') & (gdf['L12'] != '3')]
    # 处理核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_mid)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'L12'] = '3'
            row = gdf.loc[index_value]
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_mid)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'L12'] = '3'
                row = gdf.loc[index_value]
                if row['L13'] != '1' and row['L13'] != '3':
                    gdf.loc[index_value, 'L13'] = '3'
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l12没有需要通过弱连通分量处理显示层级的数据！")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    print("L12开始通过悬挂路逻辑处理")
    for index_value in isolated_roads:
        # 等级低者隐藏
        # isolated_roads是存储索引的列表，row通过.loc方法从gdf中获取到原gdf中的相应行
        row = gdf.loc[index_value]
        if row['L12'] == '2':
            gdf.loc[index_value, 'L13'] = '2'
            gdf.loc[index_value, 'L14'] = '2'
            gdf.loc[index_value, 'BZ'] = '悬挂路隐藏'
        # 等级高者连接
        if row['L12'] == '1':
            # 获取当前道路的节点
            road_endpoints = [{
                'road_id': index_value,
                'endpoint_type': 'start',
                'geometry_length': row['geometry'].length,
                'geometry': Point(row['geometry'].coords[0])
            }, {
                'road_id': index_value,
                'endpoint_type': 'end',
                'geometry_length': row['geometry'].length,
                'geometry': Point(row['geometry'].coords[-1])
            }]
            road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
            # 寻找匹配节点及其对应的road_id
            matched_gdf = gpd.sjoin_nearest(
                left_df=low_grade_endpoints_gdf,
                right_df=road_endpoints_gdf,
                how='inner',
                max_distance=tolerance_mid,
            )
            if not matched_gdf.empty:
                # 直接处理和我们当前悬挂路点连接的
                for road_index in matched_gdf.index:
                    index_value = matched_gdf.loc[road_index]['road_id_left']
                    gdf.loc[index_value, 'L12'] = '3'
                    gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                    row = gdf.loc[index_value]
                    if row['L13'] != '1' and row['L13'] != '3':
                        gdf.loc[index_value, 'L13'] = '3'
                    if row['L14'] != '1' and row['L14'] != '3':
                        gdf.loc[index_value, 'L14'] = '3'
                    if row['L15'] != '1' and row['L15'] != '3':
                        gdf.loc[index_value, 'L15'] = '3'
                    if row['L16'] != '1' and row['L16'] != '3':
                        gdf.loc[index_value, 'L16'] = '3'
                    if row['L17'] != '1' and row['L17'] != '3':
                        gdf.loc[index_value, 'L17'] = '3'
    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("L12悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L12'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            row = gdf.loc[index_value]
            if row['L13'] != '1' and row['L13'] != '3':
                gdf.loc[index_value, 'L13'] = '3'
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'

    return gdf


# l13处理
def process_l13(component_gdfs, gdf, g):
    # 筛选等级低于13级的道路
    gdf_pro = gdf[(gdf['L13'] != '1') & (gdf['L13'] != '3')]
    # 处理核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_mid)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'L13'] = '3'
            row = gdf.loc[index_value]
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_mid)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'L13'] = '3'
                row = gdf.loc[index_value]
                if row['L14'] != '1' and row['L14'] != '3':
                    gdf.loc[index_value, 'L14'] = '3'
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l13没有通过弱连通分量需要处理显示层级的数据！")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    print("L13开始通过悬挂路逻辑处理")
    print(isolated_roads)
    for index_value in isolated_roads:
        # 等级低者隐藏
        # isolated_roads是存储索引的列表，row通过.loc方法从gdf中获取到原gdf中的相应行
        row = gdf.loc[index_value]
        if row['L12'] == '2':
            gdf.loc[index_value, 'L13'] = '2'
            gdf.loc[index_value, 'L14'] = '2'
            gdf.loc[index_value, 'BZ'] = '悬挂路隐藏'
        # 等级高者连接
        if row['L12'] == '1':
            # 获取当前道路的节点
            road_endpoints = [{
                'road_id': index_value,
                'endpoint_type': 'start',
                'geometry_length': row['geometry'].length,
                'geometry': Point(row['geometry'].coords[0])
            }, {
                'road_id': index_value,
                'endpoint_type': 'end',
                'geometry_length': row['geometry'].length,
                'geometry': Point(row['geometry'].coords[-1])
            }]
            road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
            # 寻找匹配节点及其对应的road_id
            matched_gdf = gpd.sjoin_nearest(
                left_df=low_grade_endpoints_gdf,
                right_df=road_endpoints_gdf,
                how='inner',
                max_distance=tolerance_mid,
            )
            if not matched_gdf.empty:
                # 直接处理和我们当前悬挂路点连接的
                for road_index in matched_gdf.index:
                    index_value = matched_gdf.loc[road_index]['road_id_left']
                    gdf.loc[index_value, 'L13'] = '3'
                    row = gdf.loc[index_value]
                    if row['L14'] != '1' and row['L14'] != '3':
                        gdf.loc[index_value, 'L14'] = '3'
                    if row['L15'] != '1' and row['L15'] != '3':
                        gdf.loc[index_value, 'L15'] = '3'
                    if row['L16'] != '1' and row['L16'] != '3':
                        gdf.loc[index_value, 'L16'] = '3'
                    if row['L17'] != '1' and row['L17'] != '3':
                        gdf.loc[index_value, 'L17'] = '3'
                    gdf.loc[index_value, 'BZ'] = '悬挂路连通'
    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("l13悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L13'] = '3'
            row = gdf.loc[index_value]
            if row['L14'] != '1' and row['L14'] != '3':
                gdf.loc[index_value, 'L14'] = '3'
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
    return gdf


# L14处理
def process_l14(component_gdfs, gdf, g):
    gdf_pro = gdf[(gdf['L14'] != '1') & (gdf['L14'] != '3')]
    # 处理核心逻辑
    connecting_roads_df, low_grade_endpoints_gdf = process_core(component_gdfs, gdf_pro, tolerance_mid)
    print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    #  只保留连接同一对最近点对的最短道路
    if not connecting_roads_df.empty:
        idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
        #  首先获取最短道路在原始gdf中的索引
        shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
        for index_value in shortest_road_indices:
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
            gdf.loc[index_value, 'L14'] = '3'
            row = gdf.loc[index_value]
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
    else:
        # 返回的结果是一个list
        ids = process_assist(component_gdfs, gdf_pro, tolerance_mid)
        if ids:
            for index_value in ids:
                gdf.loc[index_value, 'BZ'] = '悬挂路连通'
                gdf.loc[index_value, 'L14'] = '3'
                row = gdf.loc[index_value]
                if row['L15'] != '1' and row['L15'] != '3':
                    gdf.loc[index_value, 'L15'] = '3'
                if row['L16'] != '1' and row['L16'] != '3':
                    gdf.loc[index_value, 'L16'] = '3'
                if row['L17'] != '1' and row['L17'] != '3':
                    gdf.loc[index_value, 'L17'] = '3'
        else:
            print("l14没有通过弱连通分量处理的显示层级的数据！")
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    # 开始做相应处理
    print("L14开始通过悬挂路逻辑处理")
    for index_value in isolated_roads:
        # 等级低者隐藏, 这里注意isolated_roads是一个存储road_id--road_index的列表
        row = gdf.loc[index_value]
        if row['L12'] == '2':
            gdf.loc[index_value, 'L14'] = '2'
            gdf.loc[index_value, 'BZ'] = '悬挂路隐藏'
        # 等级高者连接
        if row['L12'] == '1':
            # 获取当前道路的节点
            road_endpoints = [{
                'road_id': index_value,
                'endpoint_type': 'start',
                'geometry_length': row['geometry'].length,
                'geometry': Point(row['geometry'].coords[0])
            }, {
                'road_id': index_value,
                'endpoint_type': 'end',
                'geometry_length': row['geometry'].length,
                'geometry': Point(row['geometry'].coords[-1])
            }]
            road_endpoints_gdf = gpd.GeoDataFrame(road_endpoints, crs="EPSG:4540")
            # 寻找匹配节点及其对应的road_id
            matched_gdf = gpd.sjoin_nearest(
                left_df=low_grade_endpoints_gdf,
                right_df=road_endpoints_gdf,
                how='inner',
                max_distance=tolerance_mid,
            )
            if not matched_gdf.empty:
                # 直接处理和我们当前悬挂路点连接的
                for road_index in matched_gdf.index:
                    index_value = matched_gdf.loc[road_index]['road_id_left']
                    gdf.loc[index_value, 'L14'] = '3'
                    row = gdf.loc[index_value]
                    if row['L15'] != '1' and row['L15'] != '3':
                        gdf.loc[index_value, 'L15'] = '3'
                    if row['L16'] != '1' and row['L16'] != '3':
                        gdf.loc[index_value, 'L16'] = '3'
                    if row['L17'] != '1' and row['L17'] != '3':
                        gdf.loc[index_value, 'L17'] = '3'
                    gdf.loc[index_value, 'BZ'] = '悬挂路连通'

    # 处理一端相连的悬挂路
    d_matched_gdf = gpd.sjoin_nearest(
        left_df=low_grade_endpoints_gdf,
        right_df=dangling_roads_gdf,
        how='inner',
        max_distance=tolerance_mid,
    )
    print("L14悬挂路一端情况")
    print(d_matched_gdf)
    if not d_matched_gdf.empty:
        # 直接处理和我们当前悬挂路点连接的
        for road_index in d_matched_gdf.index:
            index_value = d_matched_gdf.loc[road_index]['road_id_left']
            gdf.loc[index_value, 'L14'] = '3'
            # 索引到当前行的series
            row = gdf.loc[index_value]
            if row['L15'] != '1' and row['L15'] != '3':
                gdf.loc[index_value, 'L15'] = '3'
            if row['L16'] != '1' and row['L16'] != '3':
                gdf.loc[index_value, 'L16'] = '3'
            if row['L17'] != '1' and row['L17'] != '3':
                gdf.loc[index_value, 'L17'] = '3'
            gdf.loc[index_value, 'BZ'] = '悬挂路连通'
    return gdf


# L15处理，着重悬挂路问题
def process_l15(gdf, g):
    isolated_roads, dangling_roads_gdf = get_processed_roads(g)
    print("L15悬挂处理开始：")
    # 开始做相应处理
    for index_value, row in dangling_roads_gdf.iterrows():
        # 获取在原gdf中的索引road_id = road_index
        road_id = row['road_id']
        # 低等级隐藏
        if gdf.loc[road_id, 'L14'] == '2':
            gdf.loc[road_id, 'L15'] = '2'
            gdf.loc[road_id, 'BZ'] = '悬挂路隐藏'

    for index_value in isolated_roads:
        print(f"isolatedL15:{index_value}")
        row = gdf.loc[index_value]
        if row['L14'] == '2':
            gdf.loc[index_value, 'L15'] = '2'
            gdf.loc[index_value, 'BZ'] = '悬挂路隐藏'
    return gdf
    # gdf_pro = gdf[(gdf['L15'] != '1') | (gdf['L15'] != '3')]
    # # 处理核心逻辑
    # connecting_roads_df = process_core(component_gdfs, gdf_pro, tolerance_low)
    # print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    # #  只保留连接同一对最近点对的最短道路
    # if not connecting_roads_df.empty:
    #     idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
    #     #  首先获取最短道路在原始gdf中的索引
    #     shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
    #     for index_value in shortest_road_indices:
    #         gdf.loc[index_value, 'L15'] = '3'
    #         row = gdf.loc[index_value]
    #         if row['L16'] != '1' or row['L16'] != '3':
    #             gdf.loc[index_value, 'L16'] = '3'
    #         if row['L17'] != '1' or row['L17'] != '3':
    #             gdf.loc[index_value, 'L17'] = '3'
    # else:
    #     # 返回的结果是一个list
    #     ids = process_assist(component_gdfs, gdf_pro, tolerance_low)
    #     if ids:
    #         for index_value in ids:
    #             gdf.loc[index_value, 'L15'] = '3'
    #             row = gdf.loc[index_value]
    #             if row['L16'] != '1' or row['L16'] != '3':
    #                 gdf.loc[index_value, 'L16'] = '3'
    #             if row['L17'] != '1' or row['L17'] != '3':
    #                 gdf.loc[index_value, 'L17'] = '3'
    #     else:
    #         print("l15没有需要处理显示层级的数据！")
    # return gdf


# # L16数据处理
# def process_l16(gdf, g):
#     isolated_roads, dangling_roads_gdf = get_processed_roads(g)
#     print("悬挂结果")
#     print(dangling_roads_gdf)
#     # 开始做相应处理
#     for index_value, row in dangling_roads_gdf.iterrows():
#         # 获取在原gdf中的索引road_id = road_index
#         road_id = row['road_id']
#         if gdf.loc[road_id, 'L14'] == '2':
#             gdf.loc[road_id, 'L15'] = '2'
#             gdf.loc[road_id, 'BZ'] = '悬挂路隐藏'
#
#     for index_value in isolated_roads:
#         print(f"isolatedL15:{index_value}")
#         row = gdf.loc[index_value]
#         if row['L14'] == '2':
#             gdf.loc[index_value, 'L15'] = '2'
#     return gdf
    # gdf_pro = gdf[(gdf['L16'] != '1') | (gdf['L16'] != '3')]
    # print(gdf_pro)
    # # 处理核心逻辑
    # connecting_roads_df = process_core(component_gdfs, gdf_pro, tolerance_low)
    # print(connecting_roads_df[['road_id', 'geometry_length_start', 'pair_id_start', 'pair_id_end']].to_string())
    # #  只保留连接同一对最近点对的最短道路
    # if not connecting_roads_df.empty:
    #     idx = connecting_roads_df.groupby('pair_id_start')['geometry_length_start'].idxmin()
    #     #  首先获取最短道路在原始gdf中的索引
    #     shortest_road_indices = connecting_roads_df.loc[idx]['road_id']
    #     for index_value in shortest_road_indices:
    #         gdf.loc[index_value, 'L16'] = '3'
    #         row = gdf.loc[index_value]
    #         if row['L17'] != '1' or row['L17'] != '3':
    #             gdf.loc[index_value, 'L17'] = '3'
    # else:
    #     # 返回的结果是一个list
    #     ids = process_assist(component_gdfs, gdf_pro, tolerance_low)
    #     if ids:
    #         for index_value in ids:
    #             gdf.loc[index_value, 'L16'] = '3'
    #             row = gdf.loc[index_value]
    #             if row['L17'] != '1' or row['L17'] != '3':
    #                 gdf.loc[index_value, 'L17'] = '3'
    #     else:
    #         print("l16没有需要处理显示层级的数据！")
    # return gdf


def show_graph(g):
    # --- 5. 可视化路网 ---
    print("\n正在可视化路网...")
    plt.figure(figsize=(10, 8))

    # 获取节点位置，用于绘图
    # NetworkX 节点现在存储了原始的 (x, y) 坐标
    node_pos = nx.get_node_attributes(g, 'pos')

    if node_pos:  # 确保有节点位置数据
        # nx.draw(g, node_pos, with_labels=True, node_color='skyblue', edge_color='gray', node_size=10)

        # 绘制节点
        nx.draw_networkx_nodes(g, node_pos, node_color='skyblue', node_size=10)
        # 绘制边
        # 如果是DiGraph，会显示箭头
        nx.draw_networkx_edges(g, node_pos, edge_color='gray', width=0.5, alpha=0.7)

        # 可以选择不绘制节点标签，因为路网节点通常太多
        # nx.draw_networkx_labels(G, node_pos, font_size=8, font_color='black')
        plt.title(" Shapefile to graph")
        plt.xlabel("lon")
        plt.ylabel("lat")
        plt.axis('equal')  # 保持地图的纵横比
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.show()
    else:
        print("没有节点位置信息，无法绘制图。")


# 应该传入一个gdf参数给函数，测试时先不要--合并到界面时需要
def network():
    gdf = gpd.read_file(r"D:\智能电子地图项目\路网测试数据\0821.txt\0821.shp")
    # 和一阶段合并，从那边传入gdf
    # 先对数据进行复制
    gdf_copy = gdf.copy()
    print(gdf_copy.dtypes)
    # L7开始处理
    current_vis_roads_gdf = gdf_copy[gdf_copy['L7'] == '1']
    g_current_vis, components = build_graph_from_gdf(current_vis_roads_gdf)   # 对于上一步提取的数据建立路网!!!!!!!
    # # 测试可行度：
    # show_graph(g_current_vis)
    # ！！！！！处理悬挂！！！！！！
    if len(components) > 1:
        print(f"Network is disconnected into {len(components)} componenets.")
        # 传入图和components，得到一个是一系列弱连通分量内的节点gdf组成的列表
        component_gdfs = get_components_geometry(components, g_current_vis)
        # 开始处理L7的路网问题
        gdf_copy = process_l7(component_gdfs, gdf_copy, g_current_vis)
    else:
        print("Network is connected!")

    # L8处理
    current_vis_roads_gdf1 = gdf_copy[(gdf_copy['L8'] == '1') | (gdf_copy['L8'] == '3')]
    print(current_vis_roads_gdf1)
    # 建立路网
    g_current_vis1, components1 = build_graph_from_gdf(current_vis_roads_gdf1)
    # show_graph(g_current_vis1)
    # ！处理悬挂
    if len(components1) > 1:
        print(f"Network is disconnected into {len(components1)} componenets.")
        # 传入图和components，得到一个是每个弱连通分量内的节点的gdf组成的gdf的列表
        component_gdfs1 = get_components_geometry(components1, g_current_vis1)
        # print(component_gdfs1)
        # 开始处理L8的路网问题
        gdf_copy = process_l8(component_gdfs1, gdf_copy, g_current_vis1)
    else:
        print("Network is connected!")

    # L9处理
    # current是用来建立路网的
    current_vis_roads_gdf2 = gdf_copy[(gdf_copy['L9'] == '1') | (gdf_copy['L9'] == '3')]
    g_current_vis2, components2 = build_graph_from_gdf(current_vis_roads_gdf2)
    # 画图尽量一个一个去画，不画时就注释掉
    # show_graph(g_current_vis2)
    # 处理悬挂路
    if len(components2) > 1:
        print(f"Network is disconnected into {len(components2)} componenets.")
        component_gdfs2 = get_components_geometry(components2, g_current_vis2)
        print(component_gdfs2)
        # 开始处理L9路网问题
        gdf_copy = process_l9(component_gdfs2, gdf_copy, g_current_vis2)
    else:
        print("Network is connected")

    # L10处理
    current_vis_roads_gdf3 = gdf_copy[(gdf_copy['L10'] == '1') | (gdf_copy['L10'] == '3')]
    g_current_vis3, components3 = build_graph_from_gdf(current_vis_roads_gdf3)
    # show_graph(g_current_vis3)
    # 处理悬挂路
    if len(components3) > 1:
        print(f"Network is disconnected into {len(components3)} componenets.")
        component_gdfs3 = get_components_geometry(components3, g_current_vis3)
        # 开始处理L10的路网问题
        gdf_copy = process_l10(component_gdfs3, gdf_copy, g_current_vis3)
    else:
        print("Network is connected")

    # L11处理
    current_vis_roads_gdf4 = gdf_copy[(gdf_copy['L11'] == '1') | (gdf_copy['L11'] == '3')]
    g_current_vis4, components4 = build_graph_from_gdf(current_vis_roads_gdf4)
    # show_graph(g_current_vis4)
    # 处理悬挂路
    if len(components4) > 1:
        print(f"Network is disconnected into {len(components4)} componenets.")
        component_gdfs4 = get_components_geometry(components4, g_current_vis4)
        # 开始处理L11的路网问题
        gdf_copy = process_l11(component_gdfs4, gdf_copy, g_current_vis4)
    else:
        print("Network is connected")

    # L12处理
    current_vis_roads_gdf5 = gdf_copy[(gdf_copy['L12'] == '1') | (gdf_copy['L12'] == '3')]
    g_current_vis5, components5 = build_graph_from_gdf(current_vis_roads_gdf5)
    # show_graph(g_current_vis5)
    if len(components5) > 1:
        print(f"Network is disconnected into{len(components5)}components.")
        component_gdfs5 = get_components_geometry(components5, g_current_vis5)
        # 开始处理L12的数据
        gdf_copy = process_l12(component_gdfs5, gdf_copy, g_current_vis5)
    else:
        print("Network is connected")

    # L13处理
    current_vis_roads_gdf6 = gdf_copy[(gdf_copy['L13'] == '1') | (gdf_copy['L13'] == '3')]
    g_current_vis6, components6 = build_graph_from_gdf(current_vis_roads_gdf6)
    # show_graph(g_current_vis6)
    if len(components6) > 1:
        print(f"Network is disconnected into{len(components6)}components.")
        component_gdfs6 = get_components_geometry(components6, g_current_vis6)
        # 开始处理L13的数据
        gdf_copy = process_l13(component_gdfs6, gdf_copy, g_current_vis6)
    else:
        print("Network is connected")

    # L14处理
    current_vis_roads_gdf7 = gdf_copy[(gdf_copy['L14'] == '1') | (gdf_copy['L14'] == '3')]
    g_current_vis7, components7 = build_graph_from_gdf(current_vis_roads_gdf7)
    # show_graph(g_current_vis7)
    if len(components7) > 1:
        print(f"Network is disconnected into{len(components7)}components.")
        component_gdfs7 = get_components_geometry(components7, g_current_vis7)
        # 开始处理L14的数据
        gdf_copy = process_l14(component_gdfs7, gdf_copy, g_current_vis7)
    else:
        print("Network is connected")

    # L15处理
    current_vis_roads_gdf8 = gdf_copy[(gdf_copy['L15'] == '1') | (gdf_copy['L15'] == '3')]
    g_current_vis8, components8 = build_graph_from_gdf(current_vis_roads_gdf8)
    # show_graph(g_current_vis8)
    if len(components8) > 1:
        print(f"Network is disconnected into{len(components8)}components.")
        # component_gdfs8 = get_components_geometry(components8, g_current_vis8)   # 暂时没用到，后面再做决断
        # 开始处理L15的数据---这里采用悬挂路隐藏来做
        gdf_copy = process_l15(gdf_copy, g_current_vis8)
    else:
        print("Network is connected")

    # L16处理
    current_vis_roads_gdf9 = gdf_copy[(gdf_copy['L16'] == '1') | (gdf_copy['L16'] == '3')]
    g_current_vis9, components9 = build_graph_from_gdf(current_vis_roads_gdf9)
    # show_graph(g_current_vis9)
    if len(components9) > 1:
        print(f"Network is disconnected into{len(components9)}components.")
        # component_gdfs9 = get_components_geometry(components9, g_current_vis9)
        # 开始处理L16数据
        # gdf_copy = process_l16(gdf_copy, g_current_vis9)
    else:
        print("Network is connected")

    # # 输出数据查看
    gdf_copy.to_file(r"D:\智能电子地图项目\结果存储\six0821")
    # return gdf_copy


# 调用测试
network()
