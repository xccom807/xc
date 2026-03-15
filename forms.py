from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    BooleanField,
    SubmitField,
    TextAreaField,
    SelectField,
    DecimalField,
)
from wtforms.fields.datetime import DateTimeLocalField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional
from wtforms.validators import NumberRange


class SignUpForm(FlaskForm):
    username = StringField("用户名", validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField("邮箱", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("密码", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "确认密码",
        validators=[DataRequired(), EqualTo("password", message="两次输入的密码不一致")],
    )
    full_name = StringField("全名", validators=[Optional(), Length(max=120)])
    phone = StringField("电话", validators=[Optional(), Length(max=50)])
    location = StringField("所在地", validators=[Optional(), Length(max=120)])
    submit = SubmitField("注册")


class LoginForm(FlaskForm):
    email = StringField("邮箱", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("密码", validators=[DataRequired()])
    remember_me = BooleanField("记住我")
    submit = SubmitField("登录")


class RequestHelpForm(FlaskForm):
    title = StringField("标题", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("描述", validators=[DataRequired(), Length(min=10)])
    category = SelectField(
        "分类",
        choices=[
            ("Cooking", "烹饪"),
            ("Cleaning", "清洁"),
            ("Moving", "搬运"),
            ("Tutoring", "辅导"),
            ("Errands", "跑腿"),
            ("Technical", "技术支持"),
            ("Other", "其他"),
        ],
        validators=[DataRequired()],
    )
    location = StringField("地点", validators=[Optional(), Length(max=120)])
    datetime_needed = DateTimeLocalField(
        "所需日期和时间", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )
    duration_estimate = StringField("预计时长", validators=[Optional(), Length(max=120)])
    price_offered = DecimalField("出价", places=2, rounding=None, validators=[Optional()])
    is_volunteer = BooleanField("这是志愿服务/免费请求")
    skills_required = StringField("所需技能", validators=[Optional(), Length(max=200)])
    notes = TextAreaField("补充说明", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("发布求助")


class OfferHelpForm(FlaskForm):
    message = TextAreaField("给求助者的留言", validators=[DataRequired(), Length(min=5, max=2000)])
    availability = BooleanField("我有空并且可以开始")
    timeframe = StringField("预计完成时间", validators=[Optional(), Length(max=120)])
    submit = SubmitField("提交帮助")


class NGOForm(FlaskForm):
    name = StringField("公益组织名称", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("描述", validators=[DataRequired(), Length(min=20)])
    category = SelectField(
        "分类",
        choices=[
            ("Education", "教育"),
            ("Healthcare", "医疗健康"),
            ("Environment", "环境保护"),
            ("Poverty Alleviation", "扶贫"),
            ("Animal Welfare", "动物福利"),
            ("Women & Children", "妇女儿童"),
            ("Disaster Relief", "灾害救援"),
            ("Other", "其他"),
        ],
        validators=[Optional()],
    )
    location = StringField("所在地", validators=[Optional(), Length(max=200)])
    contact_email = StringField("联系邮箱", validators=[Optional(), Email(), Length(max=200)])
    website = StringField("网站", validators=[Optional(), Length(max=300)])
    submit = SubmitField("提交审核")


class ProfileForm(FlaskForm):
    full_name = StringField("全名", validators=[Optional(), Length(max=120)])
    phone = StringField("电话", validators=[Optional(), Length(max=50)])
    location = StringField("所在地", validators=[Optional(), Length(max=120)])
    bio = TextAreaField("关于我", validators=[Optional(), Length(max=2000)])
    skills = StringField("技能", validators=[Optional(), Length(max=300)])
    avatar_url = StringField("头像 URL", validators=[Optional(), Length(max=300)])
    latitude = DecimalField("纬度", places=6, rounding=None, validators=[Optional(), NumberRange(min=-90, max=90)])
    longitude = DecimalField("经度", places=6, rounding=None, validators=[Optional(), NumberRange(min=-180, max=180)])
    submit = SubmitField("保存更改")


class ForgotPasswordForm(FlaskForm):
    email = StringField("邮箱", validators=[DataRequired(), Email(), Length(max=120)])
    submit = SubmitField("发送重置链接")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("新密码", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "确认新密码",
        validators=[DataRequired(), EqualTo("password", message="两次输入的密码不一致")],
    )
    submit = SubmitField("重置密码")


class AcceptOfferForm(FlaskForm):
    submit = SubmitField("接受帮助")


class CompleteTaskForm(FlaskForm):
    submit = SubmitField("标记为已完成")


class ReviewForm(FlaskForm):
    rating = SelectField(
        "评分",
        choices=[("5", "★★★★★"), ("4", "★★★★"), ("3", "★★★"), ("2", "★★"), ("1", "★")],
        validators=[DataRequired()],
    )
    comment = TextAreaField("评论", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("提交评价")
