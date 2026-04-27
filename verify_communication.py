#!/usr/bin/env python3
"""
验证 Text2Cypher 系统服务间通信
"""

import asyncio
import json
import sys
from typing import Dict, Any

import httpx


class ServiceCommunicationTester:
    def __init__(self):
        self.services = {
            "cypher-generator-agent": "http://localhost:8000",
            "testing-agent": "http://localhost:8003",
            "repair-agent": "http://localhost:8002",
        }
        self.timeout = 30.0

    def build_submission_payload(
        self,
        *,
        task_id: str,
        question_text: str,
        generated_cypher: str,
        generation_run_id: str,
        input_prompt_snapshot: str,
    ) -> Dict[str, Any]:
        """构造当前测试服务要求的 submission 契约。"""
        return {
            "id": task_id,
            "question": question_text,
            "generation_run_id": generation_run_id,
            "generated_cypher": generated_cypher,
            "input_prompt_snapshot": input_prompt_snapshot,
        }

    async def test_service_health(self) -> Dict[str, bool]:
        """测试各服务健康状态"""
        results = {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for service_name, url in self.services.items():
                try:
                    response = await client.get(f"{url}/health")
                    results[service_name] = response.status_code == 200
                    print(f"✅ {service_name}: 健康检查通过")
                except Exception as e:
                    results[service_name] = False
                    print(f"❌ {service_name}: 健康检查失败 - {e}")
        return results

    async def test_cypher_generator_agent(self) -> Dict[str, Any]:
        """测试 cypher-generator-agent 提交入口。"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                payload = {
                    "id": "comm-test-001",
                    "question": "查询网络设备及其端口",
                }

                response = await client.post(
                    f"{self.services['cypher-generator-agent']}/api/v1/qa/questions",
                    json=payload,
                )

                if response.status_code == 204:
                    print("✅ cypher-generator-agent: QA 任务接收成功")
                    return {"success": True, "status_code": 204}

                print(f"❌ cypher-generator-agent: 提交失败 - {response.status_code}")
                return {"success": False, "error": response.text}
            except Exception as e:
                print(f"❌ cypher-generator-agent: 连接失败 - {e}")
                return {"success": False, "error": str(e)}

    async def test_testing_service_golden(self) -> Dict[str, Any]:
        """测试测试服务的标准答案接收"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                payload = {
                    "id": "comm-test-001",
                    "cypher": "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name AS device_name, p.name AS port_name LIMIT 10",
                    "answer": [{"device_name": "test-device", "port_name": "test-port"}],
                    "difficulty": "L3"
                }
                
                response = await client.post(
                    f"{self.services['testing-agent']}/api/v1/qa/goldens",
                    json=payload,
                )
                
                if response.status_code == 200:
                    result = response.json()
                    print("✅ 测试服务: 标准答案提交成功")
                    return {"success": True, "result": result}
                else:
                    print(f"❌ 测试服务: 标准答案提交失败 - {response.status_code}")
                    return {"success": False, "error": response.text}
                    
            except Exception as e:
                print(f"❌ 测试服务: 连接失败 - {e}")
                return {"success": False, "error": str(e)}

    async def test_submission_to_testing(self) -> Dict[str, Any]:
        """测试向测试服务提交生成结果，由测试服务负责执行 TuGraph。"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # 先确保标准答案存在
                await self.test_testing_service_golden()

                payload = self.build_submission_payload(
                    task_id="comm-test-001",
                    question_text="查询网络设备及其端口",
                    generated_cypher=(
                        "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) "
                        "RETURN ne.name AS device_name, p.name AS port_name LIMIT 10"
                    ),
                    generation_run_id="comm-run-001",
                    input_prompt_snapshot="请根据 network_schema_v10 生成一个合法 Cypher，只返回 cypher 字段。",
                )
                
                response = await client.post(
                    f"{self.services['testing-agent']}/api/v1/evaluations/submissions",
                    json=payload,
                )

                if response.status_code == 200:
                    result = response.json()
                    print("✅ 测试服务: 查询结果提交成功")
                    return {"success": True, "result": result}
                else:
                    print(f"❌ 测试服务: 查询结果提交失败 - {response.status_code}")
                    return {"success": False, "error": response.text}
                    
            except Exception as e:
                print(f"❌ 测试服务: 连接失败 - {e}")
                return {"success": False, "error": str(e)}

    async def test_repair_service(self, ticket_id: str = None) -> Dict[str, Any]:
        """测试修复服务"""
        if not ticket_id:
            print("⚠️  跳过修复服务测试 - 没有提供问题单ID")
            return {"success": True, "message": "skipped"}
            
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # 获取问题单
                ticket_response = await client.get(
                    f"{self.services['testing']}/api/v1/issues/{ticket_id}"
                )
                
                if ticket_response.status_code != 200:
                    print(f"❌ 修复服务: 获取问题单失败 - {ticket_response.status_code}")
                    return {"success": False, "error": ticket_response.text}
                
                ticket_data = ticket_response.json()
                
                # 提交到修复服务
                response = await client.post(
                    f"{self.services['repair-agent']}/api/v1/issue-tickets",
                    json=ticket_data,
                )
                
                if response.status_code == 200:
                    result = response.json()
                    print("✅ 修复服务: 问题单提交成功")
                    return {"success": True, "result": result}
                else:
                    print(f"❌ 修复服务: 问题单提交失败 - {response.status_code}")
                    return {"success": False, "error": response.text}
                    
            except Exception as e:
                print(f"❌ 修复服务: 连接失败 - {e}")
                return {"success": False, "error": str(e)}

    async def test_cross_service_communication(self):
        """测试跨服务通信"""
        print("\n🔍 开始跨服务通信测试...")
        
        # 1. 健康检查
        print("\n1. 健康检查")
        health_results = await self.test_service_health()
        
        if not all(health_results.values()):
            print("\n❌ 健康检查失败，请确保所有服务都已启动")
            return False
        
        # 2. 测试查询生成服务
        print("\n2. 测试 cypher-generator-agent")
        query_result = await self.test_cypher_generator_agent()
        
        # 3. 测试测试服务
        print("\n3. 测试测试服务")
        golden_result = await self.test_testing_service_golden()
        
        # 4. 测试生成结果提交
        print("\n4. 测试生成结果提交")
        submission_result = await self.test_submission_to_testing()
        
        ticket_id = None
        if submission_result.get("success") and "ticket_id" in submission_result:
            ticket_id = submission_result["ticket_id"]
        
        # 5. 测试修复服务
        print("\n5. 测试修复服务")
        repair_result = await self.test_repair_service(ticket_id)
        
        # 总结
        print("\n📊 测试结果总结:")
        test_results = [
            ("服务健康检查", all(health_results.values())),
            ("cypher-generator-agent 提交入口", query_result.get("success", False)),
            ("标准答案提交", golden_result.get("success", False)),
            ("生成结果提交", submission_result.get("success", False)),
            ("修复服务处理", repair_result.get("success", False))
        ]
        
        all_passed = True
        for test_name, passed in test_results:
            status = "✅ 通过" if passed else "❌ 失败"
            print(f"  {test_name}: {status}")
            if not passed:
                all_passed = False
        
        if all_passed:
            print("\n🎉 所有测试通过！服务间通信正常。")
        else:
            print("\n⚠️  部分测试失败，请检查服务配置和网络连接。")
        
        return all_passed


async def main():
    print("🧪 Text2Cypher 系统服务间通信验证")
    print("=" * 50)
    
    tester = ServiceCommunicationTester()
    success = await tester.test_cross_service_communication()
    
    if success:
        print("\n✅ 验证完成 - 系统可以正常工作")
        sys.exit(0)
    else:
        print("\n❌ 验证失败 - 系统存在问题")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
