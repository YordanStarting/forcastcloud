import pymysql
pymysql.version_info = (2, 2, 1, "final", 0) # Simula la versión requerida
pymysql.install_as_MySQLdb()

from django.db.backends.base.base import BaseDatabaseWrapper
BaseDatabaseWrapper.check_database_version_supported = lambda x: None