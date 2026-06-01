"""
MySQL 数据库备份脚本（Python版本）
自动查找 MySQL 安装路径并执行备份
"""
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
import getpass

# 常见的 MySQL 安装路径
MYSQL_PATHS = [
    r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
    r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysqldump.exe",
    r"C:\xampp\mysql\bin\mysqldump.exe",
    r"C:\wamp64\bin\mysql\mysql8.0.30\bin\mysqldump.exe",
    r"C:\laragon\bin\mysql\mysql-8.0.30\bin\mysqldump.exe",
]

# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "port": "3306",
    "user": "root",
    "database": "modelhub"
}


def find_mysqldump():
    """查找 mysqldump.exe 的路径"""
    print("正在查找 mysqldump.exe...")

    for path in MYSQL_PATHS:
        if os.path.exists(path):
            print(f"✓ 找到: {path}")
            return path

    print("✗ 未找到 mysqldump.exe，请手动输入完整路径")
    manual_path = input("请输入 mysqldump.exe 的完整路径: ").strip()

    if os.path.exists(manual_path):
        return manual_path
    else:
        print(f"✗ 路径不存在: {manual_path}")
        sys.exit(1)


def backup_database(mysqldump_path, password):
    """执行数据库备份"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"modelhub_backup_{timestamp}.sql"
    backup_path = Path(backup_file).resolve()

    print(f"\n{'='*60}")
    print("  MySQL 数据库备份")
    print(f"{'='*60}")
    print(f"数据库: {DB_CONFIG['database']}")
    print(f"备份文件: {backup_path}")
    print(f"{'='*60}\n")

    print("开始备份...")

    try:
        # 构建命令
        cmd = [
            mysqldump_path,
            f"-h{DB_CONFIG['host']}",
            f"-P{DB_CONFIG['port']}",
            f"-u{DB_CONFIG['user']}",
            f"-p{password}",
            DB_CONFIG['database'],
            f"--result-file={backup_path}",
            "--default-character-set=utf8mb4"
        ]

        # 执行备份
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )

        if result.returncode == 0:
            file_size = backup_path.stat().st_size / 1024  # KB

            print(f"\n{'='*60}")
            print("  ✓ 备份成功！")
            print(f"{'='*60}")
            print(f"备份文件: {backup_path}")
            print(f"文件大小: {file_size:.2f} KB")
            print(f"{'='*60}\n")

            return backup_path
        else:
            print(f"\n✗ 备份失败！")
            print(f"错误信息: {result.stderr}")
            sys.exit(1)

    except Exception as e:
        print(f"\n✗ 备份过程出错: {str(e)}")
        sys.exit(1)


def main():
    """主函数"""
    print("\n" + "="*60)
    print("  ModelHub 数据库备份工具")
    print("="*60 + "\n")

    # 查找 mysqldump
    mysqldump_path = find_mysqldump()

    # 获取密码
    password = getpass.getpass("请输入 MySQL root 密码: ")

    # 执行备份
    backup_file = backup_database(mysqldump_path, password)

    print("备份完成！可以继续进行权限系统迁移了。\n")


if __name__ == "__main__":
    main()
