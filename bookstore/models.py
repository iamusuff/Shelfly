from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import datetime

class Customer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=15)
    address = models.TextField()
    registration_date = models.DateTimeField(auto_now_add=True)
    is_first_time_buyer = models.BooleanField(default=True)

    def __str__(self):
        return self.user.username


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=100)
    category = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    stock = models.PositiveIntegerField()
    description = models.TextField(blank=True, null=True)
    isbn = models.CharField(max_length=13, blank=True, null=True)
    cover_image = models.ImageField(upload_to='book_covers/', blank=True, null=True)

    def __str__(self):
        return self.title
    
    @property
    def get_cover_image_url(self):
        """Return cover image URL or placeholder"""
        if self.cover_image:
            return self.cover_image.url
        return '/static/images/no-cover.png'


class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage'),
    ]
    
    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES)
    discount_value = models.DecimalField(max_digits=8, decimal_places=2)
    max_usage = models.PositiveIntegerField(default=100)
    current_usage = models.PositiveIntegerField(default=0)
    min_purchase = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    expiry_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.get_discount_type_display()}"
    
    def is_valid(self):
        """Check if coupon is valid and can be used"""
        if not self.is_active:
            return False, "This coupon is inactive"
        
        if self.current_usage >= self.max_usage:
            return False, "Coupon usage limit reached"
        
        if datetime.now() > self.expiry_date.replace(tzinfo=None):
            return False, "This coupon has expired"
        
        return True, "Valid"
    
    def calculate_discount(self, amount):
        """Calculate discount based on discount type"""
        if self.discount_type == 'fixed':
            return min(self.discount_value, amount)
        else:  # percentage
            return (amount * self.discount_value) / 100


class CouponUsage(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    order = models.ForeignKey('Order', on_delete=models.CASCADE)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('coupon', 'order')

    def __str__(self):
        return f"{self.coupon.code} - Order #{self.order.id}"


class Order(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Confirmed', 'Confirmed'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    order_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    
    # Delivery Information
    delivery_name = models.CharField(max_length=100, default='N/A')
    delivery_phone = models.CharField(max_length=15, default='N/A')
    delivery_address = models.TextField(default='N/A')
    delivery_notes = models.TextField(blank=True, null=True)
    
    # Shipping and Discount
    shipping_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    applied_coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True)
    coupon_discount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    order_value_discount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    first_time_discount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    discount_code_used = models.CharField(max_length=50, blank=True, null=True)

    cancellation_reason = models.TextField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)


    def __str__(self):
        return f"Order #{self.id} - {self.customer.user.username}"
    
    @property
    def subtotal(self):
        """Calculate subtotal (items only, without shipping)"""
        return sum(item.subtotal for item in self.orderitem_set.all())
    
    @property
    def total_discount(self):
        """Calculate total discount applied"""
        return self.coupon_discount + self.order_value_discount + self.first_time_discount
    
    @property
    def total_amount(self):
        """Calculate total amount including shipping and after discounts"""
        return self.subtotal - self.total_discount + self.shipping_fee

    class Meta:
        ordering = ['-order_date']


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    subtotal = models.DecimalField(max_digits=8, decimal_places=2)

    def save(self, *args, **kwargs):
        self.unit_price = self.book.price
        self.subtotal = self.unit_price * self.quantity
        
        # Only reduce stock for new order items
        if not self.pk:
            if self.book.stock >= self.quantity:
                self.book.stock -= self.quantity
                self.book.save()
            else:
                raise ValidationError(f"Insufficient stock for {self.book.title}")
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.book.title} x {self.quantity}"


class Payment(models.Model):
    PAYMENT_METHODS = [
        ('Cash', 'Cash on Delivery'),
        ('Card', 'Credit/Debit Card'),
    ]
    
    PAYMENT_STATUS = [
        ('Unpaid', 'Unpaid'),
        ('Paid', 'Paid'),
        ('Failed', 'Failed'),
        ('Refunded', 'Refunded'),
    ]
    
    order = models.OneToOneField(Order, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=50, choices=PAYMENT_METHODS)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='Unpaid')
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment for Order #{self.order.id} - {self.status}"


class Cart(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE)
    applied_coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart - {self.customer.user.username}"
    
    @property
    def subtotal(self):
        """Calculate cart subtotal (items only)"""
        return sum(item.subtotal for item in self.cartitem_set.all())
    
    @property
    def shipping_fee(self):
        """Calculate shipping fee based on cart"""
        return self.calculate_shipping()
    
    @property
    def coupon_discount(self):
        """Calculate coupon discount if applied"""
        if self.applied_coupon:
            is_valid, msg = self.applied_coupon.is_valid()
            if is_valid and self.subtotal >= self.applied_coupon.min_purchase:
                return self.applied_coupon.calculate_discount(self.subtotal)
        return Decimal('0.00')
    
    @property
    def order_value_discount(self):
        """Calculate auto discount based on order value"""
        subtotal = self.subtotal
        if subtotal >= 5000:
            return subtotal * Decimal('0.15')
        elif subtotal >= 2000:
            return subtotal * Decimal('0.10')
        elif subtotal >= 1000:
            return subtotal * Decimal('0.05')
        return Decimal('0.00')
    
    @property
    def first_time_discount(self):
        """Calculate first-time buyer discount (15%)"""
        if self.customer.is_first_time_buyer:
            return self.subtotal * Decimal('0.15')
        return Decimal('0.00')
    
    @property
    def total_discount(self):
        """Calculate total discount"""
        return self.coupon_discount + self.order_value_discount + self.first_time_discount
    
    @property
    def total_amount(self):
        """Calculate total including shipping and after discounts"""
        return self.subtotal - self.total_discount + self.shipping_fee
    
    @property
    def total_items(self):
        """Count total items in cart"""
        return sum(item.quantity for item in self.cartitem_set.all())
    
    def calculate_shipping(self):
        """
        Shipping calculation logic:
        - Free shipping for orders above Rs. 5000
        - Rs. 50 for orders below Rs. 5000
        - Rs. 10 per book if more than 5 books
        """
        subtotal = self.subtotal
        total_items = self.total_items
        
        # Free shipping for orders above Rs. 5000
        if subtotal >= 5000:
            return Decimal('0.00')
        
        # Base shipping fee
        base_fee = Decimal('50.00')
        
        # Additional fee for more than 5 books
        if total_items > 5:
            additional_fee = (total_items - 5) * Decimal('10.00')
            return base_fee + additional_fee
        
        return base_fee


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE)
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'book')

    def __str__(self):
        return f"{self.book.title} x {self.quantity}"
    
    @property
    def subtotal(self):
        """Calculate subtotal for this item"""
        return self.book.price * self.quantity

class ContactMessage(models.Model):
    SUBJECT_CHOICES = [
        ('order', 'Order Inquiry'),
        ('book', 'Book Recommendation'),
        ('delivery', 'Delivery Issue'),
        ('feedback', 'Feedback'),
        ('partnership', 'Partnership'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('unread', 'Unread'),
        ('read', 'Read'),
        ('resolved', 'Resolved'),
    ]
    
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15, blank=True, null=True)
    subject = models.CharField(max_length=50, choices=SUBJECT_CHOICES)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unread')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.get_subject_display()} ({self.created_at.strftime('%Y-%m-%d')})"



@receiver(post_save, sender=Payment)
def update_order_status(sender, instance, created, **kwargs):
    """Mark order as confirmed if payment is paid"""
    if instance.status == "Paid" and instance.order.status == "Pending":
        instance.order.status = "Confirmed"
        instance.order.save()