import geopandas as gpd
#处理L15-L17
def data_level_4(layer4_proj, lrdl_final,buffer_distance):
    # --- 为需要旧的公路数据创建缓冲区 ---
    # layer1_proj buffer
    layer4_proj_buffered = layer4_proj.copy()
    # 创建缓冲区几何体，这些多边形将作为“覆盖者”
    layer4_proj_buffered['缓冲几何'] = layer4_proj_buffered.geometry.buffer(buffer_distance)
    # 将缓冲几何体设置为 GeoDataFrame 的活动几何体，用于后续的空间操作
    layer4_proj_buffered = layer4_proj_buffered.set_geometry('缓冲几何')
    #sjoin方法
    sjoin_result = gpd.sjoin(
        left_df=lrdl_final,
        right_df=layer4_proj_buffered,
        how='left',
        predicate='covered_by'
    )
    print("sjoin结果")
    matched_data = sjoin_result[sjoin_result['index_right'].notnull()]
    print("\n--- 实际发生覆盖的行 (筛选后) ---")
    print(matched_data)
    if not matched_data.empty:
        print("\n--- 获取索引 ---")
        # 被覆盖物体的原始索引 (来自 gdf_points)
        # 它就是 sjoin 结果的索引
        covered_object_indices = matched_data.index
        print(f"被覆盖物体的原始索引: {covered_object_indices}")

        # 覆盖物体的原始索引 (来自 gdf_polygons)
        # 它在 sjoin 结果的 'index_right' 列中
        covering_object_indices = matched_data['index_right']
        print(f"覆盖物体的原始索引: {covering_object_indices}")

        # 遍历并显示
        print("\n--- 遍历匹配结果并显示两个索引 ---")
        for sjoin_idx, row in matched_data.iterrows():
            print(f"被覆盖物体原始索引: {sjoin_idx}, 覆盖物体原始索引: {row['index_right']}")
            #覆盖物体的索引--new layer即lrrdl_final
            idx = row['index_right']
            lrdl_final.loc[sjoin_idx, 'L15'] = layer4_proj_buffered.loc[idx, 'L15']
            lrdl_final.loc[sjoin_idx, 'L16'] = layer4_proj_buffered.loc[idx, 'L16']
            lrdl_final.loc[sjoin_idx, 'L17'] = layer4_proj_buffered.loc[idx, 'L17']
            lrdl_final.loc[sjoin_idx, 'code2_3'] = layer4_proj_buffered.loc[idx, 'CODE1']
            lrdl_final.loc[sjoin_idx, 'symbol2_3'] = layer4_proj_buffered.loc[idx, 'Symbol']
            lrdl_final.loc[sjoin_idx, 'RN'] = layer4_proj_buffered.loc[idx, 'RN']
            lrdl_final.loc[sjoin_idx, 'NAME'] = layer4_proj_buffered.loc[idx, 'NAME']
    else:
        print("\n没有找到任何覆盖关系。")

    print(lrdl_final['L15'])

    # 废弃，暂时做一个后续参考
    # for idx, row in lrdl_final.iterrows():
    #     # 获取新的数据的几何信息
    #     lrdl_geom = row.geometry
    #     print(lrdl_geom)
    #     # 使用covers,指示旧公路覆盖了新公路；返回一个布尔series
    #     covering_roads = layer4_proj_buffered.geometry.covers(lrdl_geom)
    #     # 筛选出covering_roads里为true的数据,获取的是覆盖物体的索引
    #     covered_indices = covering_roads[covering_roads].index
    #     print(covered_indices)
    #     if not covered_indices.empty:
    #         print(covered_indices)
    #         # 使用索引在覆盖数据中读取具体的行
    #         covering_elements = layer4_proj_buffered.loc[covered_indices]
    #         #使用索引读取被覆盖具体数据--新数据的loc index
    #         print("\n--- 覆盖它们的元素 ---")
    #         print(covering_elements)
    #         print(covering_elements['L15'])
    #         lrdl_final.loc[idx, 'L15'] = layer4_proj_buffered.loc[covered_indices, 'L15']
    #         lrdl_final.loc[idx, 'L16'] = layer4_proj_buffered.loc[covered_indices, 'L16']
    #         lrdl_final.loc[idx, 'L17'] = layer4_proj_buffered.loc[covered_indices, 'L17']
    #         lrdl_final.loc[idx, 'code2_3'] = layer4_proj_buffered.loc[covered_indices, 'CODE']
    #         lrdl_final.loc[idx, 'symbol2_3'] = layer4_proj_buffered.loc[covered_indices, 'Symbol']
