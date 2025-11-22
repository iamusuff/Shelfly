from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Customer, Book, Order, OrderItem, Payment, Cart, CartItem, Coupon, CouponUsage, ContactMessage

# Inline Customer info with User
class CustomerInline(admin.StackedInline):
    model = Customer
    can_delete = False
    verbose_name_plural = 'Customer Profile'


# Extend User Admin
class UserAdmin(BaseUserAdmin):
    inlines = (CustomerInline,)


# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'phone', 'address', 'registration_date', 'is_first_time_buyer')
    search_fields = ('user__username', 'user__email', 'phone')
    list_filter = ('registration_date', 'is_first_time_buyer')
    
    fields = ('user', 'phone', 'address', 'registration_date', 'is_first_time_buyer')
    readonly_fields = ('registration_date',)
    list_editable = ('phone',)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'author', 'category', 'price', 'stock', 'isbn', 'cover_image_preview')
    search_fields = ('title', 'author', 'isbn')
    list_filter = ('category',)
    
    list_editable = ('price', 'stock')
    
    fields = ('title', 'author', 'category', 'isbn', 'description', 'price', 'stock', 'cover_image')
    
    def cover_image_preview(self, obj):
        if obj.cover_image:
            return f'<img src="{obj.cover_image.url}" width="50" height="75" />'
        return "No Image"
    
    cover_image_preview.allow_tags = True
    cover_image_preview.short_description = 'Cover'


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_type', 'discount_value', 'current_usage', 'max_usage', 'min_purchase', 'expiry_date', 'is_active', 'usage_percentage')
    search_fields = ('code',)
    list_filter = ('discount_type', 'is_active', 'expiry_date')
    list_editable = ('is_active',)
    
    fields = ('code', 'discount_type', 'discount_value', 'max_usage', 'current_usage', 'min_purchase', 'expiry_date', 'is_active', 'created_at')
    readonly_fields = ('current_usage', 'created_at')
    
    def usage_percentage(self, obj):
        if obj.max_usage > 0:
            percentage = (obj.current_usage / obj.max_usage) * 100
            return f"{percentage:.1f}% ({obj.current_usage}/{obj.max_usage})"
        return "0%"
    usage_percentage.short_description = 'Usage'


@admin.register(CouponUsage)
class CouponUsageAdmin(admin.ModelAdmin):
    list_display = ('coupon', 'customer', 'order', 'used_at')
    search_fields = ('coupon__code', 'customer__user__username', 'order__id')
    list_filter = ('used_at',)
    readonly_fields = ('coupon', 'customer', 'order', 'used_at')
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('book', 'quantity', 'unit_price', 'subtotal')
    readonly_fields = ('unit_price', 'subtotal')
    can_delete = True


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'order_date', 'status', 'subtotal_display', 'total_discount_display', 'shipping_fee', 'total_amount')
    list_filter = ('status', 'order_date')
    search_fields = ('customer__user__username', 'delivery_name', 'delivery_phone')
    
    list_editable = ('status',)
    
    inlines = [OrderItemInline]
    
    fieldsets = (
        ('Order Information', {
            'fields': ('customer', 'status', 'order_date')
        }),
        ('Delivery Details', {
            'fields': ('delivery_name', 'delivery_phone', 'delivery_address', 'delivery_notes')
        }),
        ('Pricing & Discounts', {
            'fields': ('shipping_fee', 'applied_coupon', 'discount_code_used', 'coupon_discount', 'order_value_discount', 'first_time_discount')
        }),
        ('Cancellation Details', {
            'fields': ('cancellation_reason', 'cancelled_at'),
            'classes': ('collapse',),  # Makes this section collapsible
        }),
    )
    
    readonly_fields = ('order_date', 'coupon_discount', 'order_value_discount', 'first_time_discount', 'cancellation_reason', 'cancelled_at')
    
    def subtotal_display(self, obj):
        return f"Rs. {obj.subtotal}"
    subtotal_display.short_description = 'Subtotal'
    
    def total_discount_display(self, obj):
        return f"Rs. {obj.total_discount}"
    total_discount_display.short_description = 'Total Discount'


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'book', 'quantity', 'unit_price', 'subtotal')
    list_filter = ('order__order_date',)
    search_fields = ('order__id', 'book__title')
    
    fields = ('order', 'book', 'quantity', 'unit_price', 'subtotal')
    readonly_fields = ('unit_price', 'subtotal')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'amount', 'method', 'status', 'transaction_id', 'date')
    list_filter = ('status', 'method', 'date')
    search_fields = ('order__id', 'transaction_id')
    
    list_editable = ('status',)
    
    fields = ('order', 'amount', 'method', 'status', 'transaction_id', 'date')
    readonly_fields = ('date',)


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    fields = ('book', 'quantity', 'subtotal_display', 'added_at')
    readonly_fields = ('subtotal_display', 'added_at')
    
    def subtotal_display(self, obj):
        return f"Rs. {obj.subtotal}"
    subtotal_display.short_description = 'Subtotal'


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'total_items', 'subtotal_display', 'applied_coupon_display', 'total_discount_display', 'shipping_display', 'total_display', 'updated_at')
    search_fields = ('customer__user__username',)
    readonly_fields = ('created_at', 'updated_at', 'total_items', 'subtotal_display', 'shipping_display', 'total_display', 'total_discount_display')
    
    inlines = [CartItemInline]
    
    fields = ('customer', 'applied_coupon', 'created_at', 'updated_at', 'total_items', 'subtotal_display', 'total_discount_display', 'shipping_display', 'total_display')
    
    def subtotal_display(self, obj):
        return f"Rs. {obj.subtotal}"
    subtotal_display.short_description = 'Subtotal'
    
    def shipping_display(self, obj):
        if obj.shipping_fee == 0:
            return "FREE"
        return f"Rs. {obj.shipping_fee}"
    shipping_display.short_description = 'Shipping'
    
    def total_display(self, obj):
        return f"Rs. {obj.total_amount}"
    total_display.short_description = 'Total'
    
    def total_discount_display(self, obj):
        return f"Rs. {obj.total_discount}"
    total_discount_display.short_description = 'Total Discount'
    
    def applied_coupon_display(self, obj):
        if obj.applied_coupon:
            return obj.applied_coupon.code
        return "None"
    applied_coupon_display.short_description = 'Coupon'


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'cart', 'book', 'quantity', 'subtotal_display', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('cart__customer__user__username', 'book__title')
    
    list_editable = ('quantity',)
    
    fields = ('cart', 'book', 'quantity', 'added_at')
    readonly_fields = ('added_at',)
    
    def subtotal_display(self, obj):
        return f"Rs. {obj.subtotal}"
    subtotal_display.short_description = 'Subtotal'


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'status', 'created_at')
    list_filter = ('status', 'subject', 'created_at')
    search_fields = ('name', 'email', 'message')
    list_editable = ('status',)
    readonly_fields = ('name', 'email', 'phone', 'subject', 'message', 'created_at')
    
    fieldsets = (
        ('Contact Information', {
            'fields': ('name', 'email', 'phone')
        }),
        ('Message Details', {
            'fields': ('subject', 'message', 'created_at')
        }),
        ('Status', {
            'fields': ('status',)
        }),
    )
    
    def has_add_permission(self, request):
        return False 