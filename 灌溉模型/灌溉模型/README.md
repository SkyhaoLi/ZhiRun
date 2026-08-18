# 呼和浩特水肥一体化V2策略模型

面向呼和浩特露地马铃薯、甜菜、玉米和向日葵，包含三层：

1. NASA POWER真实逐日气象、SoilGrids代表性土壤和四作物阶段参数；
2. 39,600条环境—作物—传感器情景训练的ExtraTrees多输出策略模型；
3. 主水阀和A/B/C肥阀的流量闭环状态机。

## 快速开始

```powershell
python -m pip install -r requirements.txt
python scripts/train_policy_v2.py
python scripts/predict_policy_v2.py --date 2025-07-20 --crop 玉米 --area-mu 1 `
  --moisture20 18 --moisture40 20 --moisture60 22 --field-capacity 28
python scripts/simulate_controller.py
```

获取地块环境先验：

```powershell
python scripts/fetch_environment.py --latitude 40.72 --longitude 111.55
```

独立测试水量R²为0.9755，N/P/K分别为0.8476/0.8723/0.7756，灌溉判断准确率93.15%。这些分数表示模型对物理—农艺教师策略的复现能力，不代表真实增产效果或产量最优精度。

训练方法和边界见 [模型报告.md](模型报告.md)，管路、流量计和安全联锁见 [硬件与模型实施说明.md](硬件与模型实施说明.md)。
