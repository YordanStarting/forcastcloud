"""
URL configuration for forecast project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path

def loaderio_verification(request):
    return HttpResponse(
        "loaderio-a822f57576aee71a53b9c9eabd7f8d2e",
        content_type="text/plain"
    )

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('clientes.urls')),
    path("loaderio-a822f57576aee71a53b9c9eabd7f8d2e.txt", loaderio_verification),
]

