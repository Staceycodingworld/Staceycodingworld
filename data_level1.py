import geopandas as gpd
#1--表示L7-L10
def data_level_1(layer1_proj, lrdl_final, buffer_distance):
    # --- 为需要旧的公路数据创建缓冲区 ---
    # layer1_proj buffer
    layer1_proj_buffered = layer1_proj.copy()
    # 创建缓冲区几何体，这些多边形将作为“覆盖者”
    layer1_proj_buffered['缓冲几何'] = layer1_proj_buffered.geometry.buffer(buffer_distance)
    # 将缓冲几何体设置为 GeoDataFrame 的活动几何体，用于后续的空间操作
    layer1_proj_buffered = layer1_proj_buffered.set_geometry('缓冲几何')
    # sjoin方法
    sjoin_result = gpd.sjoin(
        left_df=lrdl_final,
        right_df=layer1_proj_buffered,
        how='left',
        predicate='covered_by'
    )
    print("sjoin结果")
    matched_data = sjoin_result[sjoin_result['index_right'].notnull()]
    print("\n--- 实际发生覆盖的行 (筛选后) ---")
    print(matched_data)
    if not matched_data.empty:
        cleaned_index_right = matched_data['index_right'].astype(int)
        print("\n--- 获取索引 ---")
        # 被覆盖物体的原始索引 (来自 gdf_points)
        # 它就是 sjoin 结果的索引
        covered_object_indices = matched_data.index
        print(f"被覆盖物体的原始索引: {covered_object_indices}")

        # 覆盖物体的原始索引 (来自 gdf_polygons)
        # 它在 sjoin 结果的 'index_right' 列中
        covering_object_indices = cleaned_index_right
        print(f"覆盖物体的原始索引: {covering_object_indices}")

        # 遍历并显示
        print("\n--- 遍历匹配结果并显示两个索引 ---")
        for sjoin_idx, row in matched_data.iterrows():
            print(f"被覆盖物体原始索引: {sjoin_idx}, 覆盖物体原始索引: {row['index_right']}")
            idx = row['index_right']
            lrdl_final.loc[sjoin_idx, 'L7'] = layer1_proj_buffered.loc[idx, 'L7']
            lrdl_final.loc[sjoin_idx, 'L8'] = layer1_proj_buffered.loc[idx, 'L8']
            lrdl_final.loc[sjoin_idx, 'L9'] = layer1_proj_buffered.loc[idx, 'L9']
            lrdl_final.loc[sjoin_idx, 'L10'] = layer1_proj_buffered.loc[idx, 'L10']
            lrdl_final.loc[sjoin_idx, 'L11'] = '1'
            lrdl_final.loc[sjoin_idx, 'L12'] = '1'
            lrdl_final.loc[sjoin_idx, 'L13'] = '1'
            lrdl_final.loc[sjoin_idx, 'L14'] = '1'
            lrdl_final.loc[sjoin_idx, 'L15'] = '1'
            lrdl_final.loc[sjoin_idx, 'L16'] = '1'
            lrdl_final.loc[sjoin_idx, 'L17'] = '1'
            lrdl_final.loc[sjoin_idx, 'code2_1'] = layer1_proj_buffered.loc[idx, 'CODE2']
            lrdl_final.loc[sjoin_idx, 'symbol2_1'] = layer1_proj_buffered.loc[idx, 'Symbol1']
            lrdl_final.loc[sjoin_idx, 'RN'] = layer1_proj_buffered.loc[idx, 'RN']
            lrdl_final.loc[sjoin_idx, 'NAME'] = layer1_proj_buffered.loc[idx, 'NAME']

    else:
        print("\n没有找到任何覆盖关系。")
