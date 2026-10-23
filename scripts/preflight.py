"""Deployment readiness check; never calls a paid model or reads an uploaded book."""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal.config import Config
from portal.runner import load_pipeline
from portal.quality import run_browser


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',action='store_true',help='Build synthetic sample and run real file:// checks')
    args=parser.parse_args()
    config=Config.from_env()
    checks=[]
    def add(name,passed,detail):checks.append({'name':name,'status':'pass' if passed else 'unverified','detail':detail})
    add('模型配置',config.ready,'已填写；尚未向服务商验证权限' if config.ready else '；'.join(config.readiness()))
    for module in ('pypdf','pypdfium2','PIL'):
        found=importlib.util.find_spec(module) is not None
        add(module,found,'组件可加载' if found else '缺少文档读取组件')
    node=os.environ.get('NODE_BINARY') or shutil.which('node')
    add('公式运行组件',bool(node),'可用' if node else '未找到 Node')
    config.data_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.data_dir,prefix='preflight-') as temporary:
        root=Path(temporary)
        file=root/'write-probe';file.write_text('probe')
        add('任务数据目录',file.read_text()=='probe','已实际写入和读回；不影响用户任务')
        if args.browser:
            p=load_pipeline(config.skill_dir)
            sample=p.read(config.skill_dir/'tests/fixtures/general.json')
            inv=p.read(config.skill_dir/'tests/fixtures/inventory.json')
            output=root/'sample.html'
            p.build(sample,inv,output,root)
            result=run_browser(output,root/'checks',config.browser_timeout)
            add('真实离线浏览器',result['status']=='pass',result.get('detail',''))
        else:
            add('真实离线浏览器',False,'运行 --browser 后才算验证；未把安装组件等同于通过')
    result={'checks':checks,'readyForFirstLiveTrial':all(c['status']=='pass' for c in checks),
            'liveModelCall':'未执行；首次上线需用明确授权的小样本完成真实转换验收'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['readyForFirstLiveTrial'] else 1


if __name__=='__main__':raise SystemExit(main())
