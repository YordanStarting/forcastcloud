from django import forms
from django.contrib.auth.models import User
from .models import Cliente, Pedido, Proveedor, PerfilUsuario

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = '__all__'

class PedidoForm(forms.ModelForm):
    class Meta:
        model = Pedido
        fields = [
            'proveedor',
            'comercial',
            'tipo_huevo',
            'presentacion',
            'cantidad_total',
            'semana',
            'observaciones',
        ]
        widgets = {
            'semana': forms.DateInput(attrs={'type': 'date'}),
        }


class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = [
            'nombre',
            'nit',
            'contacto',
            'telefono',
            'email',
            'activo',
        ]


class UsuarioBaseForm(forms.ModelForm):
    rol = forms.ChoiceField(choices=PerfilUsuario.ROL_CHOICES, label='Rol')

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'is_active',
        ]
        labels = {
            'username': 'Usuario',
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Correo',
            'is_active': 'Activo',
        }


class UsuarioCrearForm(UsuarioBaseForm):
    password1 = forms.CharField(
        label='ContraseÃ±a',
        widget=forms.PasswordInput
    )
    password2 = forms.CharField(
        label='Confirmar contraseÃ±a',
        widget=forms.PasswordInput
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Las contraseÃ±as no coinciden.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
            PerfilUsuario.objects.update_or_create(
                usuario=user,
                defaults={'rol': self.cleaned_data['rol']}
            )
        return user


class UsuarioEditarForm(UsuarioBaseForm):
    password1 = forms.CharField(
        label='Nueva contraseÃ±a',
        widget=forms.PasswordInput,
        required=False
    )
    password2 = forms.CharField(
        label='Confirmar nueva contraseÃ±a',
        widget=forms.PasswordInput,
        required=False
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 or password2:
            if password1 != password2:
                self.add_error('password2', 'Las contraseÃ±as no coinciden.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password1 = self.cleaned_data.get('password1')
        if password1:
            user.set_password(password1)
        if commit:
            user.save()
            PerfilUsuario.objects.update_or_create(
                usuario=user,
                defaults={'rol': self.cleaned_data['rol']}
            )
        return user
