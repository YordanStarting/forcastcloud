from django.db import models
from django.contrib.auth.models import User

TIPO_HUEVO_CHOICES = [
    ('HELU', 'Huevo Líquido Entero'),
    ('YELU', 'Yema Líquida'),
    ('CLLU', 'Clara Líquida'),
    ('MEPU', 'Mezcla en Polvo'),
]

PRESENTACION_CHOICES = [
    ('OV20_1000', 'OV20 1000'),
    ('OV15_200', 'OV15 200'),
    ('OV15_20', 'OV15 20'),
    ('OV15_15', 'OV15 15'),
    ('OV15_14', 'OV15 14'),
    ('OV30_20', 'OV30-20'),
    ('OV30_10', 'OV30-10'),
    ('OV30_5', 'OV30-5'),
    ('OV30_3', 'OV30-3'),
    ('SAC_20', 'Sac x 20'),
    ('BOLSA_4_4KG', 'Bolsa 4,4Kg'),
]

CIUDAD_CHOICES = [
    ('BOGOTA', 'Bogota'),
    ('MEDELLIN', 'Medellin'),
    ('CALI', 'Cali'),
]

class Cliente(models.Model):
    id = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=100)
    imagen = models.ImageField(upload_to='imagenes/', verbose_name="Imagen", null=True)
    descripcion = models.TextField(max_length=500)

    def __str__(self):
        return f"{self.titulo} - {self.descripcion[:50]}..."
    
    def delete(self, *args, **kwargs):
        if self.imagen:
            self.imagen.delete(save=False)
        super().delete(*args, **kwargs)

class Proveedor(models.Model):
    nombre = models.CharField(max_length=150, default='Proveedor sin nombre')
    ciudad = models.CharField(max_length=20, choices=CIUDAD_CHOICES, default='BOGOTA')
    presentacion = models.CharField(
        max_length=20,
        choices=PRESENTACION_CHOICES,
        default='OV20_1000'
    )
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

class PerfilUsuario(models.Model):
    ROL_CHOICES = [
        ('admin', 'Administrador'),
        ('comercial', 'Comercial'),
        ('logistica', 'Logistica'),
        ('produccion', 'Produccion'),
        ('programador', 'Programador'),
    ]
    usuario = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)
    ciudad = models.CharField(max_length=20, choices=CIUDAD_CHOICES, default='BOGOTA')
    foto_perfil = models.ImageField(upload_to='perfiles/', null=True, blank=True)

    def __str__(self):
        return f"{self.usuario.username} - {self.rol}"

class Notificacion(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True)
    mensaje = models.TextField()
    tipo_evento = models.CharField(
        max_length=30,
        choices=[
            ('INFO', 'Informacion'),
            ('PEDIDO_CREADO', 'Pedido creado'),
            ('PEDIDO_CONFIRMADO', 'Pedido confirmado'),
            ('PEDIDO_CANCELADO', 'Pedido cancelado'),
            ('PEDIDO_DEVUELTO', 'Pedido devuelto'),
            ('PEDIDO_CAMBIO_ESTADO', 'Cambio de estado'),
        ],
        default='INFO',
    )
    reproducir_sonido = models.BooleanField(default=False)
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        if self.usuario:
            return f"Notificación para {self.usuario.username}"
        return f"Notificación: {self.mensaje[:50]}..."

class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('CONFIRMADO', 'Confirmado'),
        ('EN_PRODUCCION', 'En produccion'),
        ('DESPACHADO', 'Despachado'),
        ('ENTREGADO', 'Entregado'),
        ('CANCELADO', 'Cancelado'),
        ('DEVUELTO', 'Devuelto'),
    ]
    
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    comercial = models.ForeignKey(User, on_delete=models.PROTECT)
    ciudad = models.CharField(max_length=20, choices=CIUDAD_CHOICES, default='BOGOTA')
    
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
        max_length=20,
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


class RegistroEstadoPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        related_name='registros_estado',
        on_delete=models.CASCADE
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    estado_anterior = models.CharField(
        max_length=20,
        choices=Pedido.ESTADO_CHOICES
    )
    estado_nuevo = models.CharField(
        max_length=20,
        choices=Pedido.ESTADO_CHOICES
    )
    descripcion = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']

    def __str__(self):
        return (
            f"Pedido #{self.pedido_id}: {self.estado_anterior} -> "
            f"{self.estado_nuevo}"
        )


