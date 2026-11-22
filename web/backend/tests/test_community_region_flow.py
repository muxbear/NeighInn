"""C 端小区选择：行政区划四级联动与小区区划信息回显。"""

import pytest

from src.db.models import Resident
from tests.conftest import ADMIN_BASE, C_BASE, admin_login, bearer, register_user


async def _children(client, headers, parent_id: int | None = None) -> list[dict]:
    params = {"parentId": parent_id} if parent_id else {}
    resp = await client.get(f"{C_BASE}/regions/children", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _admin_children(client, headers, parent_id: int | None = None) -> list[dict]:
    url = (f"{ADMIN_BASE}/regions/roots" if parent_id is None
           else f"{ADMIN_BASE}/regions/{parent_id}/children")
    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_region_cascade_and_community_region_path(client):
    result = await register_user(client)
    headers = bearer(result["token"])

    provinces = await _children(client, headers)
    assert provinces and all(item["level"] == "PROVINCE" for item in provinces)
    zhejiang = next(item for item in provinces if item["name"] == "浙江省")

    cities = await _children(client, headers, int(zhejiang["id"]))
    hangzhou = next(item for item in cities if item["name"] == "杭州市")

    districts = await _children(client, headers, int(hangzhou["id"]))
    xihu = next(item for item in districts if item["name"] == "西湖区")

    streets = await _children(client, headers, int(xihu["id"]))
    wenxin = next(item for item in streets if item["name"] == "文新街道")

    resp = await client.get(
        f"{C_BASE}/communities/search",
        params={"streetId": wenxin["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    communities = resp.json()["data"]
    assert communities and all(item["streetId"] == wenxin["id"] for item in communities)

    target = next(item for item in communities if item["name"] == "阳光花园小区")
    assert target["province"] == "浙江省"
    assert target["city"] == "杭州市"
    assert target["district"] == "西湖区"
    assert target["street"] == "文新街道"
    assert target["regionPath"] == "浙江省 杭州市 西湖区 文新街道"

    # 不强制选择街道：按区县返回所有小区；按地市与关键词也可检索。
    region_resp = await client.get(
        f"{C_BASE}/communities/search", params={"regionId": xihu["id"]}, headers=headers)
    assert region_resp.status_code == 200, region_resp.text
    region_communities = region_resp.json()["data"]
    assert len(region_communities) == 5
    assert all(item["district"] == "西湖区" for item in region_communities)

    keyword_resp = await client.get(
        f"{C_BASE}/communities/search",
        params={"regionId": xihu["id"], "keyword": "阳光"}, headers=headers)
    assert [item["name"] for item in keyword_resp.json()["data"]] == ["阳光花园小区"]

    city_resp = await client.get(
        f"{C_BASE}/communities/search", params={"cityId": hangzhou["id"]}, headers=headers)
    assert len(city_resp.json()["data"]) == 7


@pytest.mark.asyncio
async def test_nearby_communities_include_region_fields(client):
    result = await register_user(client)
    headers = bearer(result["token"])
    resp = await client.get(f"{C_BASE}/communities/nearby", headers=headers)
    assert resp.status_code == 200, resp.text
    communities = resp.json()["data"]
    assert communities
    assert all(item["regionPath"] for item in communities)


@pytest.mark.asyncio
async def test_region_children_requires_login(client):
    resp = await client.get(f"{C_BASE}/regions/children")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


def _walk(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk(node.get("children") or [])


@pytest.mark.asyncio
async def test_admin_region_tree_covers_all_provinces_and_detailed_provinces(client):
    """W04-01 社区运维左侧区划树：31 个省级行政区，北京/陕西下钻到街道。"""
    csrf = await admin_login(client)
    resp = await client.get(f"{ADMIN_BASE}/regions/tree", headers=csrf)
    assert resp.status_code == 200, resp.text
    tree = resp.json()["data"]

    provinces = [node for node in tree if node["level"] == "PROVINCE"]
    assert len(provinces) == 31
    assert provinces[0]["name"] == "浙江省"  # 默认小区所在省份保持首位

    by_name = {node["name"]: node for node in provinces}
    beijing_nodes = list(_walk(by_name["北京市"]["children"]))
    assert sum(1 for node in beijing_nodes if node["level"] == "DISTRICT") == 16
    assert sum(1 for node in beijing_nodes if node["level"] == "STREET") == 349

    shaanxi_nodes = list(_walk(by_name["陕西省"]["children"]))
    assert sum(1 for node in shaanxi_nodes if node["level"] == "CITY") == 10
    assert sum(1 for node in shaanxi_nodes if node["level"] == "DISTRICT") == 107
    assert sum(1 for node in shaanxi_nodes if node["level"] == "STREET") == 1335


def test_region_seed_dataset_is_complete_and_consistent():
    """种子区划覆盖全国四级；数据被裁剪/编码冲突时此用例直接失败。"""
    from src.db.seed import REGIONS

    levels: dict[str, int] = {}
    for _name, level, _code, _parent, _sort in REGIONS:
        levels[level] = levels.get(level, 0) + 1

    codes = [row[2] for row in REGIONS]
    code_set = set(codes)
    assert len(codes) == len(code_set), "区划编码必须唯一"
    assert levels == {"PROVINCE": 31, "CITY": 342, "DISTRICT": 3056, "STREET": 41272}
    assert all(row[3] in code_set for row in REGIONS if row[3]), "父级编码必须存在"

    sichuan_cities = [row for row in REGIONS if row[1] == "CITY" and row[3] == "510000"]
    assert len(sichuan_cities) == 21
    # 小区档案 street_id 依赖的历史夹具编码不能丢失。
    assert {"330106001", "330106002", "330106003"} <= code_set


@pytest.mark.asyncio
async def test_admin_region_lazy_loading_roots_and_children(client):
    """社区运维分级加载：roots 返回省份与子级数量，children 按需返回下一级。"""
    csrf = await admin_login(client)

    resp = await client.get(f"{ADMIN_BASE}/regions/roots", headers=csrf)
    assert resp.status_code == 200, resp.text
    roots = resp.json()["data"]
    assert len(roots) == 31
    assert all(node["level"] == "PROVINCE" for node in roots)
    assert all("childCount" in node for node in roots)

    by_name = {node["name"]: node for node in roots}
    beijing = by_name["北京市"]
    shaanxi = by_name["陕西省"]
    assert beijing["childCount"] == 1
    assert shaanxi["childCount"] == 10

    cities = (await client.get(f"{ADMIN_BASE}/regions/{beijing['id']}/children",
                               headers=csrf)).json()["data"]
    assert len(cities) == 1 and cities[0]["name"] == "市辖区"
    assert cities[0]["childCount"] == 16
    districts = (await client.get(f"{ADMIN_BASE}/regions/{cities[0]['id']}/children",
                                  headers=csrf)).json()["data"]
    assert len(districts) == 16
    assert sum(node["childCount"] for node in districts) == 349

    shaanxi_cities = (await client.get(f"{ADMIN_BASE}/regions/{shaanxi['id']}/children",
                                       headers=csrf)).json()["data"]
    assert len(shaanxi_cities) == 10
    xian = next(node for node in shaanxi_cities if node["name"] == "西安市")
    assert xian["childCount"] == 13
    xian_districts = (await client.get(f"{ADMIN_BASE}/regions/{xian['id']}/children",
                                       headers=csrf)).json()["data"]
    assert len(xian_districts) == 13
    assert sum(node["childCount"] for node in xian_districts) == 172

    # 命中进程内缓存后响应保持一致
    again = (await client.get(f"{ADMIN_BASE}/regions/roots", headers=csrf)).json()["data"]
    assert again == roots


@pytest.mark.asyncio
async def test_admin_community_create_update_delete(client):
    """新增（街道可选）/编辑/删除社区。"""
    csrf = await admin_login(client)
    roots = await _admin_children(client, csrf)
    beijing = next(node for node in roots if node["name"] == "北京市")
    city = (await _admin_children(client, csrf, int(beijing["id"])))[0]
    districts = await _admin_children(client, csrf, int(city["id"]))
    dongcheng = next(node for node in districts if node["name"] == "东城区")
    xicheng = next(node for node in districts if node["name"] == "西城区")
    xicheng_streets = await _admin_children(client, csrf, int(xicheng["id"]))
    street = xicheng_streets[0]

    payload = {
        "name": "测试花园社区", "type": "商品房社区", "address": "东华门街道测试花园",
        "regionId": int(dongcheng["id"]),
        "households": 100, "population": 300, "managerName": "测试负责人",
    }
    resp = await client.post(f"{ADMIN_BASE}/communities", json=payload, headers=csrf)
    assert resp.status_code == 200, resp.text
    created = resp.json()["data"]
    community_id = created["id"]
    assert created["regionId"] == dongcheng["id"]
    assert created["streetId"] == ""  # 街道可选项，未选择时不写入
    assert created["longitude"] is None and created["latitude"] is None  # 经纬度选填
    assert created["code"].startswith("SQ")

    duplicate = await client.post(f"{ADMIN_BASE}/communities", json=payload, headers=csrf)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == 40901

    update_payload = {
        **payload,
        "name": "测试花园社区（西区）",
        "regionId": int(xicheng["id"]),
        "streetId": int(street["id"]),
        "status": "PREPARING",
        "longitude": 116.366,
        "latitude": 39.912,
    }
    resp = await client.put(f"{ADMIN_BASE}/communities/{community_id}",
                            json=update_payload, headers=csrf)
    assert resp.status_code == 200, resp.text
    updated = resp.json()["data"]
    assert updated["name"] == "测试花园社区（西区）"
    assert updated["regionId"] == xicheng["id"]
    assert updated["streetId"] == street["id"]
    assert updated["status"] == "PREPARING"
    assert updated["longitude"] == 116.366

    # 编辑时可显式清空经纬度
    resp = await client.put(
        f"{ADMIN_BASE}/communities/{community_id}",
        json={**update_payload, "longitude": None, "latitude": None},
        headers=csrf,
    )
    assert resp.status_code == 200, resp.text
    cleared = resp.json()["data"]
    assert cleared["longitude"] is None and cleared["latitude"] is None

    resp = await client.delete(f"{ADMIN_BASE}/communities/{community_id}", headers=csrf)
    assert resp.status_code == 200, resp.text
    resp = await client.get(f"{ADMIN_BASE}/communities/{community_id}", headers=csrf)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_community_delete_is_blocked_by_business_data(client, db_session):
    csrf = await admin_login(client)
    db_session.add(Resident(community_id=1, name="占用业主", certification_status="VERIFIED"))
    await db_session.commit()

    resp = await client.delete(f"{ADMIN_BASE}/communities/1", headers=csrf)
    assert resp.status_code == 409
    assert "业主档案" in resp.json()["message"]


@pytest.mark.asyncio
async def test_admin_community_batch_import(client):
    csrf = await admin_login(client)
    roots = await _admin_children(client, csrf)
    beijing = next(node for node in roots if node["name"] == "北京市")
    city = (await _admin_children(client, csrf, int(beijing["id"])))[0]
    districts = await _admin_children(client, csrf, int(city["id"]))
    xicheng = next(node for node in districts if node["name"] == "西城区")
    street_name = (await _admin_children(client, csrf, int(xicheng["id"])))[0]["name"]

    items = [
        {"name": "批量导入社区A", "districtName": "东城区",
         "households": 100, "population": 200, "status": "正常运营"},
        {"name": "批量导入社区B", "districtName": "西城区", "streetName": street_name,
         "longitude": 116.37, "latitude": 39.91, "status": "筹备中"},
        {"name": "批量导入社区C", "districtName": "不存在区", "longitude": 116.4,
         "latitude": 39.9},
        {"name": "批量导入社区A", "districtName": "东城区", "longitude": 116.41,
         "latitude": 39.91},
    ]
    resp = await client.post(f"{ADMIN_BASE}/communities/import",
                             json={"cityId": int(city["id"]), "items": items}, headers=csrf)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["created"] == 2
    assert data["failed"] == 2
    assert {error["row"] for error in data["errors"]} == {3, 4}

    listed = (await client.get(f"{ADMIN_BASE}/communities",
                               params={"cityId": int(city["id"]), "pageSize": 50},
                               headers=csrf)).json()["data"]["items"]
    names = {row["name"] for row in listed}
    assert {"批量导入社区A", "批量导入社区B"} <= names


@pytest.mark.asyncio
async def test_admin_communities_can_filter_by_city(client):
    csrf = await admin_login(client)
    tree = (await client.get(f"{ADMIN_BASE}/regions/tree", headers=csrf)).json()["data"]
    provinces = {node["name"]: node for node in tree if node["level"] == "PROVINCE"}
    hangzhou = provinces["浙江省"]["children"][0]
    xian = next(node for node in provinces["陕西省"]["children"] if node["name"] == "西安市")

    resp = await client.get(f"{ADMIN_BASE}/communities",
                            params={"cityId": hangzhou["id"], "pageSize": 50}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 7

    resp = await client.get(f"{ADMIN_BASE}/communities",
                            params={"cityId": xian["id"]}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 0
