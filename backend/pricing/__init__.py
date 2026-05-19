"""
智能询报价 Agent 模块

架构：engine_client → state_machine → service → routes
                         ↑               ↑
                    risk_guard      insight_engine
                    trade_executor  context_inherit
"""
