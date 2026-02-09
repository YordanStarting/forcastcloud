from django.db import models
from django.contrib.auth.models import User

TIPO_HUEVO_CHOICES = [
    ('HELU', 'Huevo Líquido Entero'),
    ('YELU', 'Yema Líquida'),
    ('CLLU', 'Clara Líquida'),
    ('MEPU', 'Mezcla en Polvo'),
]

PRESENTACION_CHOICES = [
    ('OV20_1000', 'OV20 - 1000g'),
    ('OV15_200', 'OV15 - 200g'),
    ('SAC_20', 'Saco 20kg'),
    ('SAC_5', 'Saco 5kg'),
]

class Cliente(models.Model):
    id = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=100)
    imagen = models.ImageField(upload_to='imagenes/', verbose_name="Imagen", null=True)
    descripcion = models.TextField(max_length=500)  # CORREGIDO: descripcion (no desciption)

    def __str__(self):
        return f"{self.titulo} - {self.descripcion[:50]}..."
    
    def delete(self, *args, **kwargs):
        if self.imagen:
            self.imagen.delete(save=False)
        super().delete(*args, **kwargs)

class Proveedor(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    nit = models.CharField(max_length=30, blank=True, null=True)
    contacto = models.CharField(max_length=100, blank=True, null=True)
    telefono = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

class PerfilUsuario(models.Model):
    ROL_CHOICES = [
        ('comercial', 'Comercial'),
        ('logistica', 'Logística'),
        ('produccion', 'Producción'),
        ('admin', 'Administrador'),
    ]
    usuario = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)

    def __str__(self):
        return f"{self.usuario.username} - {self.rol}"

class Notificacion(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True)
    mensaje = models.TextField()
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        if self.usuario:
            return f"Notificación para {self.usuario.username}"
        return f"Notificación: {self.mensaje[:50]}..."

class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('EN_PROCESO', 'En proceso'),
        ('REALIZADO', 'Realizado'),  # Coincide con tu views.py
    ]
    
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    comercial = models.ForeignKey(User, on_delete=models.PROTECT)
    
    tipo_huevo = models.CharField(max_length=10, choices=TIPO_HUEVO_CHOICES)
    presentacion = models.CharField(max_length=20, choices=PRESENTACION_CHOICES)
    
    # CAMPOS QUE USAS EN LAS VISTAS:
    cantidad = models.IntegerField(default=0)
    fecha_entrega = models.DateField(null=True, blank=True)
    
    # Campos adicionales (si los necesitas):
    cantidad_total = models.IntegerField(default=0)
    semana = models.DateField(
        help_text="Lunes de la semana", 
        null=True, 
        blank=True
    )
    
    estado = models.CharField(
        max_length=15,
        choices=ESTADO_CHOICES,
        default='PENDIENTE'
    )
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    observaciones = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Pedido #{self.id} - {self.proveedor.nombre}"

class EntregaPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        related_name='entregas',
        on_delete=models.CASCADE
    )
    
    fecha_entrega = models.DateField()
    cantidad = models.IntegerField()
    
    estado = models.CharField(
        max_length=10,
        choices=[
            ('PENDIENTE', 'Pendiente'),
            ('ENTREGADO', 'Entregado'),
        ],
        default='PENDIENTE'
    )
    
    def __str__(self):
        return f"Entrega para Pedido #{self.pedido.id} - {self.fecha_entrega}"